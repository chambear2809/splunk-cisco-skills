"""Render the Splunk Observability Isovalent Integration overlay + helpers.

Composes a Splunk OTel collector agent.config overlay with seven Prometheus
scrape jobs for Cilium / Hubble / Envoy / Cilium operator / Tetragon agent
+ operator (and optional cilium-dnsproxy), a strict filter/includemetrics
allow-list, and the file-based Splunk Platform logs path
(extraFileLogs.filelog/tetragon + agent.extraVolumes hostPath mount). The
overlay is designed to merge with the base values produced by
splunk-observability-otel-collector-setup via yq deep-merge.

Outputs:
  - splunk-otel-overlay/values.overlay.yaml
  - dashboards/<name>.json   (token-scrubbed re-exports when --dashboards-source is set)
  - detectors/<name>.yaml
  - scripts/handoff-base-collector.sh
  - scripts/handoff-hec-token.sh
  - scripts/handoff-cisco-security-cloud.sh
  - scripts/handoff-dashboards.sh
  - scripts/handoff-detectors.sh
  - scripts/scrub-tokens.py
  - metadata.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SHARED_LIB = Path(__file__).resolve().parents[3] / "skills" / "shared" / "lib"
if str(SHARED_LIB) not in sys.path:
    sys.path.insert(0, str(SHARED_LIB))

from yaml_compat import YamlCompatError, dump_yaml, load_yaml_or_json  # noqa: E402


SKILL_NAME = "splunk-observability-isovalent-integration"
DEFAULT_TETRAGON_HOST_PATH = "/var/run/cilium/tetragon"
DEFAULT_TETRAGON_FILENAME_PATTERN = "*.log"
ALLOWED_REALMS = {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}
ALLOWED_DISTRIBUTIONS = {"openshift", "kubernetes", "eks", "gke"}
ALLOWED_EXPORT_MODES = {"file", "stdout", "fluentd"}
INDEX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
SOURCETYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:.-]{0,255}$")
MAX_TOKEN_BYTES = 16 * 1024

# Default metric allow-list. Curated from the production Gruve atl-ocp2
# deployment values + the Isovalent_Splunk_o11y reference repo. The goal:
# enough series to power the standard cilium/hubble/tetragon dashboards
# without flooding O11y with high-cardinality kernel-level event noise.
DEFAULT_METRIC_ALLOWLIST = [
    # Cilium
    "cilium_api_limiter_processed_requests_total",
    "cilium_bpf_map_ops_total",
    "cilium_endpoint_state",
    "cilium_errors_warnings_total",
    "cilium_hive_status",
    "cilium_ip_addresses",
    "cilium_ipam_capacity",
    "cilium_kubernetes_events_total",
    "cilium_policy_l7_total",
    "cilium_proxy_upstream_reply_seconds_bucket",
    # Hubble
    "hubble_dns_queries_total",
    "hubble_dns_responses_total",
    "hubble_drop_total",
    "hubble_flows_processed_total",
    "hubble_http_request_duration_seconds_bucket",
    "hubble_http_requests_total",
    "hubble_icmp_total",
    "hubble_policy_verdicts_total",
    "hubble_tcp_flags_total",
    # Tetragon
    "tetragon_events_total",
    "tetragon_dns_total",
    "tetragon_http_response_total",
    "tetragon_socket_stats_retransmitsegs_total",
    "tetragon_socket_stats_rxbytes_total",
    "tetragon_socket_stats_txbytes_total",
    "tetragon_socket_stats_udp_rxbytes_total",
    "tetragon_socket_stats_udp_txbytes_total",
    "tetragon_network_connect_total",
    "tetragon_network_close_total",
    # Host
    "system.cpu.utilization",
    "system.memory.utilization",
    "system.network.io",
    "system.network.errors",
    # Kubernetes
    "k8s.node.cpu.utilization",
    "k8s.node.memory.usage",
    "k8s.pod.cpu.utilization",
    "k8s.pod.memory.usage",
    "k8s.namespace.phase",
]


class SpecError(ValueError):
    pass


def _mapping(value: Any, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SpecError(f"{name} must be a mapping.")
    return value


def _nonempty_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SpecError(
            f"{name} must be a nonempty string without surrounding whitespace."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SpecError(f"{name} contains control characters.")
    return value


def validate_hec_url(value: str) -> str:
    if not value:
        return ""
    value = _nonempty_string(value, name="Splunk Platform HEC URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SpecError("Splunk Platform HEC URL must be an absolute https:// URL.")
    if parsed.username is not None or parsed.password is not None:
        raise SpecError("Splunk Platform HEC URL must not contain user information.")
    if parsed.query or parsed.fragment:
        raise SpecError("Splunk Platform HEC URL must not contain a query or fragment.")
    try:
        parsed.port
    except ValueError as exc:
        raise SpecError("Splunk Platform HEC URL contains an invalid port.") from exc
    return value.rstrip("/")


def validate_token_file(
    path_value: str, *, flag: str, allow_loose_permissions: bool = False
) -> str:
    """Validate a credential reference without reading or serializing its value."""

    if not path_value:
        return ""
    path = Path(path_value).expanduser().absolute()
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise SpecError(f"{flag} must reference an existing credential file.") from exc
    if stat.S_ISLNK(info.st_mode):
        raise SpecError(f"{flag} must not be a symbolic link.")
    if not stat.S_ISREG(info.st_mode):
        raise SpecError(f"{flag} must reference a regular file.")
    if info.st_uid != os.geteuid():
        raise SpecError(f"{flag} must be owned by the current user.")
    if info.st_nlink != 1:
        raise SpecError(f"{flag} must have exactly one hard link.")
    if stat.S_IMODE(info.st_mode) != 0o600 and not allow_loose_permissions:
        raise SpecError(f"{flag} must be mode 600.")
    if info.st_size <= 0 or info.st_size > MAX_TOKEN_BYTES:
        raise SpecError(f"{flag} has an invalid size.")
    return str(path)


def effective_scrape_jobs(spec: dict[str, Any]) -> list[str]:
    scrape = _mapping(spec.get("scrape"), name="scrape")
    job_flags = (
        ("cilium_agent_9962", "prometheus/isovalent_cilium", True),
        ("hubble_metrics_9965", "prometheus/isovalent_hubble", True),
        ("cilium_envoy_9964", "prometheus/isovalent_envoy", True),
        ("cilium_operator_9963", "prometheus/isovalent_operator", True),
        ("tetragon_2112", "prometheus/isovalent_tetragon", True),
        ("tetragon_operator_2113", "prometheus/isovalent_tetragon_operator", True),
        ("cilium_dnsproxy", "prometheus/isovalent_dnsproxy", False),
    )
    jobs: list[str] = []
    for key, receiver, default in job_flags:
        enabled = scrape.get(key, default)
        if not isinstance(enabled, bool):
            raise SpecError(f"scrape.{key} must be true or false.")
        if enabled:
            jobs.append(receiver)
    if not jobs:
        raise SpecError("At least one Isovalent Prometheus scrape job must be enabled.")
    return jobs


def representative_signalflow_metrics(spec: dict[str, Any]) -> dict[str, str]:
    validation = _mapping(spec.get("validation"), name="validation")
    configured = _mapping(
        validation.get("signalflow_metrics"),
        name="validation.signalflow_metrics",
    )
    defaults = {
        "cilium": "cilium_endpoint_state",
        "hubble": "hubble_flows_processed_total",
        "tetragon": "tetragon_dns_total",
    }
    unknown = sorted(set(configured) - set(defaults))
    if unknown:
        raise SpecError(
            "validation.signalflow_metrics contains unsupported metric families."
        )
    result: dict[str, str] = {}
    for family, default in defaults.items():
        metric = configured.get(family, default)
        if (
            not isinstance(metric, str)
            or not re.fullmatch(r"[A-Za-z_:][A-Za-z0-9_.:/-]{0,511}", metric)
            or not metric.startswith(f"{family}_")
        ):
            raise SpecError(
                f"validation.signalflow_metrics.{family} must be a {family}_* metric name."
            )
        result[family] = metric
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--distribution", default="")
    parser.add_argument("--export-mode", default="")
    parser.add_argument("--legacy-fluentd-hec", default="false")
    parser.add_argument("--platform-hec-url", default="")
    parser.add_argument("--platform-hec-token-file", default="")
    parser.add_argument("--render-platform-hec-helper", default="false")
    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--dashboards-source", default="")
    parser.add_argument("--allow-loose-token-perms", default="false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def bool_flag(value: str) -> bool:
    return str(value).lower() == "true"


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = load_yaml_or_json(text, source=str(path))
    except YamlCompatError as exc:
        raise SpecError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec {path} did not parse to a mapping.")
    if data.get("api_version") != f"{SKILL_NAME}/v1":
        raise SpecError(
            f"Spec api_version must be '{SKILL_NAME}/v1'; got {data.get('api_version')!r}"
        )
    return data


def normalize_configuration(
    args: argparse.Namespace, spec: dict[str, Any]
) -> dict[str, Any]:
    for flag_name, value in (
        ("--legacy-fluentd-hec", args.legacy_fluentd_hec),
        ("--render-platform-hec-helper", args.render_platform_hec_helper),
        ("--allow-loose-token-perms", args.allow_loose_token_perms),
    ):
        if str(value).lower() not in {"true", "false"}:
            raise SpecError(f"{flag_name} must be true or false.")

    realm = args.realm or spec.get("realm", "us0")
    if not isinstance(realm, str) or realm not in ALLOWED_REALMS:
        raise SpecError(
            "realm must be one of: " + ", ".join(sorted(ALLOWED_REALMS)) + "."
        )
    cluster_name = _nonempty_string(
        args.cluster_name or spec.get("cluster_name", "lab-cluster"),
        name="cluster_name",
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}", cluster_name):
        raise SpecError("cluster_name contains unsupported characters.")
    distribution = args.distribution or spec.get("distribution", "kubernetes")
    if not isinstance(distribution, str) or distribution not in ALLOWED_DISTRIBUTIONS:
        raise SpecError(
            "distribution must be one of: "
            + ", ".join(sorted(ALLOWED_DISTRIBUTIONS))
            + "."
        )

    tetragon_export = _mapping(spec.get("tetragon_export"), name="tetragon_export")
    configured_export_mode = tetragon_export.get("mode", "file")
    if not isinstance(configured_export_mode, str):
        raise SpecError("tetragon_export.mode must be a string.")
    export_mode = args.export_mode or configured_export_mode
    if export_mode not in ALLOWED_EXPORT_MODES:
        raise SpecError(
            "export mode must be one of: "
            + ", ".join(sorted(ALLOWED_EXPORT_MODES))
            + "."
        )
    legacy_fluentd = bool_flag(args.legacy_fluentd_hec) or export_mode == "fluentd"
    if bool_flag(args.legacy_fluentd_hec):
        if args.export_mode and args.export_mode != "fluentd":
            raise SpecError(
                "--legacy-fluentd-hec cannot be combined with a non-fluentd --export-mode."
            )
        export_mode = "fluentd"

    splunk_block = _mapping(spec.get("splunk_platform"), name="splunk_platform")
    platform_enabled = splunk_block.get("enabled", True)
    if not isinstance(platform_enabled, bool):
        raise SpecError("splunk_platform.enabled must be true or false.")
    index = splunk_block.get("index", "cisco_isovalent")
    sourcetype = splunk_block.get("sourcetype", "cisco:isovalent")
    if not isinstance(index, str) or not INDEX_RE.fullmatch(index):
        raise SpecError("splunk_platform.index contains an invalid Splunk index name.")
    if not isinstance(sourcetype, str) or not SOURCETYPE_RE.fullmatch(sourcetype):
        raise SpecError("splunk_platform.sourcetype contains an invalid sourcetype.")

    hec_url = validate_hec_url(
        args.platform_hec_url or str(splunk_block.get("hec_url") or "")
    )
    allow_loose = bool_flag(args.allow_loose_token_perms)
    o11y_token_file = validate_token_file(
        args.o11y_token_file,
        flag="--o11y-token-file",
        allow_loose_permissions=allow_loose,
    )
    platform_hec_token_file = validate_token_file(
        args.platform_hec_token_file,
        flag="--platform-hec-token-file",
        allow_loose_permissions=allow_loose,
    )
    render_hec_helper = bool_flag(args.render_platform_hec_helper)
    if platform_hec_token_file and not hec_url:
        raise SpecError(
            "--platform-hec-token-file requires --platform-hec-url or splunk_platform.hec_url."
        )
    if not platform_enabled and (
        hec_url or platform_hec_token_file or render_hec_helper
    ):
        raise SpecError(
            "Splunk Platform HEC options require splunk_platform.enabled: true."
        )

    collector = _mapping(spec.get("collector"), name="collector")
    collector_fields = {
        "release": ("splunk-otel-collector", r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"),
        "namespace": ("", r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?"),
        "chart_ref": (
            "splunk-otel-collector-chart/splunk-otel-collector",
            r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+",
        ),
        "chart_version": ("", r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}"),
    }
    for key, (default, pattern) in collector_fields.items():
        value = collector.get(key, default)
        if not isinstance(value, str) or (value and not re.fullmatch(pattern, value)):
            raise SpecError(f"collector.{key} contains unsupported characters.")
    normalize_otlp = collector.get("normalize_legacy_otlphttp", "auto")
    if str(normalize_otlp).lower() not in {"auto", "true", "false"}:
        raise SpecError(
            "collector.normalize_legacy_otlphttp must be auto, true, or false."
        )
    for key in ("disable_gateway", "disable_operator"):
        if not isinstance(collector.get(key, False), bool):
            raise SpecError(f"collector.{key} must be true or false.")

    metric_allowlist = _mapping(spec.get("metric_allowlist"), name="metric_allowlist")
    extra_metrics = metric_allowlist.get("extra", [])
    if not isinstance(extra_metrics, list) or not all(
        isinstance(metric, str)
        and re.fullmatch(r"[A-Za-z_:][A-Za-z0-9_.:/-]{0,511}", metric)
        for metric in extra_metrics
    ):
        raise SpecError("metric_allowlist.extra must contain valid metric names.")

    if export_mode == "file" and platform_enabled:
        host_path = tetragon_export.get("host_path", DEFAULT_TETRAGON_HOST_PATH)
        pattern = tetragon_export.get(
            "filename_pattern", DEFAULT_TETRAGON_FILENAME_PATTERN
        )
        if not isinstance(host_path, str) or not host_path.startswith("/"):
            raise SpecError("tetragon_export.host_path must be an absolute path.")
        if (
            not isinstance(pattern, str)
            or not pattern
            or "/" in pattern
            or ".." in pattern
        ):
            raise SpecError(
                "tetragon_export.filename_pattern must be a nonempty basename glob."
            )

    effective_scrape_jobs(spec)
    representative_signalflow_metrics(spec)
    return {
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "export_mode": export_mode,
        "legacy_fluentd": legacy_fluentd,
        "hec_url": hec_url,
        "o11y_token_file": o11y_token_file,
        "platform_hec_token_file": platform_hec_token_file,
        "render_hec_helper": render_hec_helper,
    }


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_yaml(path: Path, payload: Any) -> None:
    write_text(path, dump_yaml(payload, sort_keys=True))


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def overlay_values(
    spec: dict[str, Any],
    *,
    cluster_name: str,
    distribution: str,
    export_mode: str,
    legacy_fluentd: bool,
    platform_hec_url: str,
) -> dict[str, Any]:
    collector = spec.get("collector") or {}
    scrape = spec.get("scrape") or {}
    metric_allowlist = list(DEFAULT_METRIC_ALLOWLIST)
    extras = (spec.get("metric_allowlist") or {}).get("extra") or []
    for name in extras:
        if name not in metric_allowlist:
            metric_allowlist.append(name)
    for name in representative_signalflow_metrics(spec).values():
        if name not in metric_allowlist:
            metric_allowlist.append(name)

    receivers: dict[str, Any] = {}
    pipeline_receivers: list[str] = ["hostmetrics", "kubeletstats", "otlp"]
    if scrape.get("cilium_agent_9962", True):
        receivers["prometheus/isovalent_cilium"] = _scrape_job(
            "cilium_metrics_9962", "cilium", 9962, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_cilium")
    if scrape.get("hubble_metrics_9965", True):
        receivers["prometheus/isovalent_hubble"] = _scrape_job(
            "hubble_metrics_9965", "cilium", 9965, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_hubble")
    if scrape.get("cilium_envoy_9964", True):
        receivers["prometheus/isovalent_envoy"] = _scrape_job(
            "envoy_metrics_9964", "cilium-envoy", 9964, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_envoy")
    if scrape.get("cilium_operator_9963", True):
        receivers["prometheus/isovalent_operator"] = _scrape_job_operator(
            "cilium_operator_metrics_9963", 9963
        )
        pipeline_receivers.append("prometheus/isovalent_operator")
    if scrape.get("tetragon_2112", True):
        receivers["prometheus/isovalent_tetragon"] = _scrape_job_tetragon(
            "tetragon_metrics_2112", 2112
        )
        pipeline_receivers.append("prometheus/isovalent_tetragon")
    if scrape.get("tetragon_operator_2113", True):
        receivers["prometheus/isovalent_tetragon_operator"] = (
            _scrape_job_tetragon_operator("tetragon_operator_metrics_2113", 2113)
        )
        pipeline_receivers.append("prometheus/isovalent_tetragon_operator")
    if scrape.get("cilium_dnsproxy", False):
        receivers["prometheus/isovalent_dnsproxy"] = _scrape_job(
            "cilium_dnsproxy_metrics", "cilium-dnsproxy", 9967, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_dnsproxy")

    overlay: dict[str, Any] = {
        "clusterName": cluster_name or "lab-cluster",
        "distribution": distribution or "kubernetes",
        # OpenShift requires kubeletstats to skip TLS verify (self-signed kubelet
        # certs). Other distributions accept this default safely.
        "agent": {
            "config": {
                "extensions": {
                    "k8s_observer": {
                        "auth_type": "serviceAccount",
                        "observe_pods": True,
                    },
                },
                "receivers": dict(
                    receivers,
                    **{
                        "kubeletstats": {
                            "collection_interval": "30s",
                            "insecure_skip_verify": True,
                        },
                    },
                ),
                "processors": {
                    "filter/includemetrics": {
                        "metrics": {
                            "include": {
                                "match_type": "strict",
                                "metric_names": metric_allowlist,
                            }
                        }
                    },
                    "resourcedetection": {
                        "detectors": ["system"],
                        "system": {"hostname_sources": ["os"]},
                    },
                },
                "service": {
                    "pipelines": {
                        "metrics": {
                            "exporters": ["signalfx"],
                            "receivers": pipeline_receivers,
                            "processors": [
                                "memory_limiter",
                                "batch",
                                "filter/includemetrics",
                                "resourcedetection",
                                "resource",
                            ],
                        }
                    }
                },
            }
        },
    }
    if collector.get("disable_gateway", False):
        overlay["gateway"] = {"enabled": False}
    if collector.get("disable_operator", False):
        overlay["operator"] = {"enabled": False}
        overlay["operatorcrds"] = {"installed": False}

    splunk_block = spec.get("splunk_platform") or {}
    if (
        splunk_block.get("enabled", True)
        and export_mode == "file"
        and not legacy_fluentd
    ):
        host_path = (spec.get("tetragon_export") or {}).get(
            "host_path", DEFAULT_TETRAGON_HOST_PATH
        )
        filename_pattern = (spec.get("tetragon_export") or {}).get(
            "filename_pattern", DEFAULT_TETRAGON_FILENAME_PATTERN
        )
        index = splunk_block.get("index", "cisco_isovalent")
        sourcetype = splunk_block.get("sourcetype", "cisco:isovalent")
        # The hostPath mount + extraFileLogs.filelog/tetragon block is the
        # production-validated path (see references/tetragon-hostpath-coordination.md).
        overlay["agent"]["extraVolumes"] = [
            {"name": "tetragon", "hostPath": {"path": host_path}}
        ]
        overlay["agent"]["extraVolumeMounts"] = [
            {"name": "tetragon", "mountPath": host_path}
        ]
        # The filelog/tetragon receiver is declared once, below, via the chart's
        # logsCollection.extraFileLogs block (which both defines the receiver and
        # wires it into the logs pipeline). We deliberately do NOT also add a
        # standalone agent.config.receivers.filelog/tetragon entry, which the
        # chart would treat as a redundant duplicate.
        overlay["splunkPlatform"] = {
            "logsEnabled": True,
        }
        if platform_hec_url:
            overlay["splunkPlatform"]["endpoint"] = platform_hec_url
        if splunk_block.get("insecure_skip_verify"):
            overlay["splunkPlatform"]["insecureSkipVerify"] = True
        overlay["logsCollection"] = {
            "containers": {"useSplunkIncludeAnnotation": True},
            "extraFileLogs": {
                "filelog/tetragon": {
                    "include": [f"{host_path}/{filename_pattern}"],
                    "start_at": "beginning",
                    "include_file_path": True,
                    "include_file_name": False,
                    "resource": {
                        "com.splunk.index": index,
                        "com.splunk.source": f"{host_path}/",
                        "host.name": 'EXPR(env("K8S_NODE_NAME"))',
                        "k8s.cluster.name": cluster_name,
                        "com.splunk.sourcetype": sourcetype,
                    },
                }
            },
        }
    elif (
        splunk_block.get("enabled", True)
        and export_mode == "stdout"
        and not legacy_fluentd
    ):
        # stdout mode: rely on Splunk OTel collector's container log collection.
        # Tetragon's stdout already flows through the standard logsCollection
        # pipeline; we just need to enable splunkPlatform.logsEnabled.
        overlay["splunkPlatform"] = {"logsEnabled": True}
        if platform_hec_url:
            overlay["splunkPlatform"]["endpoint"] = platform_hec_url
    elif legacy_fluentd:
        # Legacy fluentd path renders nothing in the overlay -- the Tetragon
        # Helm values already include the fluentd config (see
        # cisco-isovalent-platform-setup --export-mode fluentd). We still
        # leave splunkPlatform.logsEnabled false because the legacy path
        # doesn't use the OTel splunkhec exporter.
        pass

    return overlay


def _scrape_job(name: str, app_label: str, port: int, label_key: str) -> dict[str, Any]:
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": [
                                f"__meta_kubernetes_pod_label_{label_key}"
                            ],
                            "action": "keep",
                            "regex": app_label,
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "regex": "(.+)",
                            "replacement": "$1:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


def _scrape_job_operator(name: str, port: int) -> dict[str, Any]:
    """Cilium operator pods use the io_cilium_app=operator label.

    Note: the operator runs in its own Deployment, not the cilium DaemonSet,
    so the pod IP differs. The relabel approach still works via
    __meta_kubernetes_pod_ip.
    """
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": [
                                "__meta_kubernetes_pod_label_io_cilium_app"
                            ],
                            "action": "keep",
                            "regex": "operator",
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "regex": "(.+)",
                            "replacement": "$1:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


def _scrape_job_tetragon(name: str, port: int) -> dict[str, Any]:
    """Tetragon DaemonSet pods use app.kubernetes.io/name=tetragon."""
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": [
                                "__meta_kubernetes_pod_label_app_kubernetes_io_name"
                            ],
                            "action": "keep",
                            "regex": "tetragon",
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "regex": "(.+)",
                            "replacement": "$1:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


def _scrape_job_tetragon_operator(name: str, port: int) -> dict[str, Any]:
    """Tetragon operator metrics on port 2113."""
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": [
                                "__meta_kubernetes_pod_label_app_kubernetes_io_name"
                            ],
                            "action": "keep",
                            "regex": "tetragon-operator",
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "regex": "(.+)",
                            "replacement": "$1:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


SCRUB_TOKEN_PY = '''#!/usr/bin/env python3
"""Token scrubber for dashboard JSON re-exports.

Walks a JSON document and rewrites credential-shaped keys and values to a
placeholder before the dashboard is published.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


PLACEHOLDER = "${REDACTED}"
SECRET_KEY_PARTS = ("token", "secret", "authorization", "bearer", "password", "credential", "hec")
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:bearer|splunk)\\s+[A-Za-z0-9._+/=-]{8,}|"
    r"(?:token|secret|authorization|bearer|hec)\\s*[:=]\\s*[A-Za-z0-9._+/=-]{8,}"
)


def secret_key(key):
    normalized = "".join(character for character in str(key).lower() if character.isalnum())
    return any(part in normalized for part in SECRET_KEY_PARTS)


def walk(node):
    if isinstance(node, dict):
        return {k: _scrub(k, v) for k, v in node.items()}
    if isinstance(node, list):
        return [walk(item) for item in node]
    if isinstance(node, str) and SECRET_VALUE_RE.search(node):
        return PLACEHOLDER
    return node


def _scrub(key, value):
    if secret_key(key) and value not in (None, "", [], {}):
        return PLACEHOLDER
    return walk(value)


def main(argv):
    if len(argv) != 3:
        print(f"Usage: {argv[0]} <input.json> <output.json>", file=sys.stderr)
        return 1
    src = Path(argv[1])
    dst = Path(argv[2])
    raw = json.loads(src.read_text(encoding="utf-8"))
    scrubbed = walk(raw)
    # Defense in depth: re-scan all keys and free-form string values.
    text = json.dumps(scrubbed, indent=2, sort_keys=True)
    key_leak = re.compile(
        r'(?i)"[^"\\n]*(?:token|secret|authorization|bearer|password|credential|hec)[^"\\n]*"\\s*:\\s*"(?!\\$\\{REDACTED\\})[^"\\n]+"'
    )
    if key_leak.search(text) or SECRET_VALUE_RE.search(text):
        print("ERROR: scrubbed JSON still contains credential-shaped material.", file=sys.stderr)
        return 1
    dst.write_text(text + "\\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def render_apply_overlay_script(
    spec: dict[str, Any],
    *,
    o11y_token_file: str,
    platform_hec_token_file: str,
    platform_hec_url: str,
    export_mode: str,
) -> str:
    collector = spec.get("collector") or {}
    release = collector.get("release", "splunk-otel-collector")
    namespace = collector.get("namespace", "")
    chart_ref = collector.get(
        "chart_ref", "splunk-otel-collector-chart/splunk-otel-collector"
    )
    chart_version = collector.get("chart_version", "")
    normalize_legacy_otlphttp = str(
        collector.get("normalize_legacy_otlphttp", "auto")
    ).lower()
    o11y_token_default = shlex.quote(o11y_token_file)
    platform_hec_token_default = shlex.quote(platform_hec_token_file)
    platform_hec_url_default = shlex.quote(platform_hec_url)
    splunk_platform = spec.get("splunk_platform") or {}
    platform_enabled = splunk_platform.get("enabled", True)
    platform_index = splunk_platform.get("index", "cisco_isovalent")
    platform_sourcetype = splunk_platform.get("sourcetype", "cisco:isovalent")
    return f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

# Helm status and Kubernetes objects can contain customer data. Refuse shell
# tracing before any external command can read those objects; otherwise a
# command substitution or later refactor could disclose them through bash -x.
case $- in
    *x*)
        echo 'ERROR: shell xtrace is enabled; refusing before reading Helm or Kubernetes objects.' >&2
        exit 1
        ;;
esac

# Apply the Isovalent overlay to an existing Splunk OTel Collector helm release
# by merging this overlay onto current values and running helm upgrade.
# Honors K8S_APPLY_DRY_RUN=true (helm --dry-run).
#
# Required env: O11Y_TOKEN_FILE (path to Org access token, chmod 600), unless
# a default was supplied while rendering. PLATFORM_HEC_TOKEN_FILE and
# PLATFORM_HEC_URL are required together when Splunk Platform export is used.
# Required tooling: helm, kubectl, yq, python3.
# Cilium/Hubble/Tetragon must already be installed in the cluster.

if ! command -v helm >/dev/null 2>&1; then echo 'ERROR: helm required.' >&2; exit 1; fi
if ! command -v kubectl >/dev/null 2>&1; then echo 'ERROR: kubectl required.' >&2; exit 1; fi
if ! command -v yq >/dev/null 2>&1; then echo 'ERROR: yq required.' >&2; exit 1; fi
if ! command -v python3 >/dev/null 2>&1; then echo 'ERROR: python3 required.' >&2; exit 1; fi

if [[ -z "${{EXPECTED_KUBE_CONTEXT:-}}" ]]; then
    echo 'ERROR: EXPECTED_KUBE_CONTEXT is required; pass setup.sh --kube-context with the exact current context.' >&2
    exit 1
fi
CURRENT_KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null)" || {{
    echo 'ERROR: Could not determine the current Kubernetes context.' >&2
    exit 1
}}
if [[ "${{CURRENT_KUBE_CONTEXT}}" != "${{EXPECTED_KUBE_CONTEXT}}" ]]; then
    echo 'ERROR: Current Kubernetes context does not match EXPECTED_KUBE_CONTEXT.' >&2
    exit 1
fi
KUBECTL=(kubectl --context "${{EXPECTED_KUBE_CONTEXT}}")
HELM=(helm --kube-context "${{EXPECTED_KUBE_CONTEXT}}")

HELM_VERSION="$("${{HELM[@]}}" version --template '{{{{.Version}}}}' 2>/dev/null)" || {{
    echo 'ERROR: Could not determine the Helm client version.' >&2
    exit 1
}}
case "${{HELM_VERSION}}" in
    v4.*) ;;
    *)
        echo 'ERROR: This apply helper requires Helm 4 because --force-conflicts is mandatory.' >&2
        exit 1
        ;;
esac
HELM_UPGRADE_HELP="$("${{HELM[@]}}" upgrade --help 2>/dev/null)" || {{
    echo 'ERROR: Could not inspect Helm upgrade capabilities.' >&2
    exit 1
}}
if ! grep -q -- '--force-conflicts' <<<"${{HELM_UPGRADE_HELP}}"; then
    echo 'ERROR: Helm upgrade does not support required --force-conflicts.' >&2
    exit 1
fi
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" == "true" ]] && ! grep -q -- '--hide-secret' <<<"${{HELM_UPGRADE_HELP}}"; then
    echo 'ERROR: Helm dry-run is refused because this client cannot --hide-secret.' >&2
    exit 1
fi

if [[ -z "${{O11Y_TOKEN_FILE:-}}" ]]; then O11Y_TOKEN_FILE={o11y_token_default}; fi
if [[ -z "${{PLATFORM_HEC_TOKEN_FILE:-}}" ]]; then PLATFORM_HEC_TOKEN_FILE={platform_hec_token_default}; fi
if [[ -z "${{PLATFORM_HEC_URL:-}}" ]]; then PLATFORM_HEC_URL={platform_hec_url_default}; fi
if [[ -z "${{O11Y_TOKEN_FILE}}" ]]; then
    echo 'ERROR: O11Y_TOKEN_FILE must point to an owner-only regular token file.' >&2
    exit 1
fi
if [[ -n "${{PLATFORM_HEC_TOKEN_FILE}}" && -z "${{PLATFORM_HEC_URL}}" ]]; then
    echo 'ERROR: PLATFORM_HEC_TOKEN_FILE requires PLATFORM_HEC_URL.' >&2
    exit 1
fi

# Confirm Cilium / Tetragon presence; refuse to proceed if neither is found.
if ! "${{KUBECTL[@]}}" get ns cilium >/dev/null 2>&1 \\
   && ! "${{KUBECTL[@]}}" -n kube-system get ds cilium >/dev/null 2>&1 \\
   && ! "${{KUBECTL[@]}}" get ns isovalent-system >/dev/null 2>&1; then
    echo 'ERROR: Could not detect a Cilium/Tetragon installation (looked for ns cilium, ns isovalent-system, ds kube-system/cilium).' >&2
    echo '       Install the Isovalent platform first via skills/cisco-isovalent-platform-setup.' >&2
    exit 1
fi

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
OVERLAY="${{DIR}}/splunk-otel-overlay/values.overlay.yaml"

RELEASE="{release}"
NAMESPACE="{namespace}"
CHART_REF="{chart_ref}"
CHART_VERSION="{chart_version}"
NORMALIZE_OTLPHTTP="{normalize_legacy_otlphttp}"
PLATFORM_ENABLED="{str(platform_enabled).lower()}"
EXPORT_MODE="{export_mode}"
EXPECTED_PLATFORM_INDEX="{platform_index}"
EXPECTED_PLATFORM_SOURCETYPE="{platform_sourcetype}"
CHART_NAME="${{CHART_REF##*/}}"
RELEASE_ROWS="$("${{HELM[@]}}" list --all-namespaces --filter "^${{RELEASE}}$" -o json 2>/dev/null)" || {{
    echo 'ERROR: Could not list the expected collector Helm release.' >&2
    exit 1
}}
NAMESPACE="$(RELEASE_ROWS_JSON="${{RELEASE_ROWS}}" python3 - "${{RELEASE}}" "${{NAMESPACE}}" <<'PY'
import json
import os
import sys

release, expected_namespace = sys.argv[1:]
try:
    rows = json.loads(os.environ["RELEASE_ROWS_JSON"])
except (KeyError, json.JSONDecodeError):
    raise SystemExit("ERROR: Helm list returned invalid JSON.")
if not isinstance(rows, list):
    raise SystemExit("ERROR: Helm list did not return a release list.")
matches = [row for row in rows if isinstance(row, dict) and row.get("name") == release]
if len(matches) == 0:
    raise SystemExit("ERROR: The expected collector Helm release does not exist.")
if len(matches) != 1:
    raise SystemExit("ERROR: The collector Helm release name is ambiguous across namespaces.")
row = matches[0]
namespace = row.get("namespace")
if not isinstance(namespace, str) or not namespace:
    raise SystemExit("ERROR: Collector Helm release has no namespace.")
if expected_namespace and namespace != expected_namespace:
    raise SystemExit("ERROR: Collector Helm release namespace does not match the rendered specification.")
print(namespace)
PY
)" || exit 1
# Never retain a complete Helm release document in a shell variable. Stream
# the current notes-free metadata into one strict parser so name, namespace,
# exact chart version, and deployed status are authoritative in the same read.
# Only the strictly validated chart-version scalar is retained so an unpinned
# rendered packet can continue using the exact currently installed version.
if ! CURRENT_CHART_VERSION="$("${{HELM[@]}}" get metadata "${{RELEASE}}" --namespace "${{NAMESPACE}}" -o json 2>/dev/null \
    | python3 -c '
import json
import re
import sys

data = json.load(sys.stdin)
release, namespace, chart, expected_version = sys.argv[1:]
version = str(data.get("version") or "") if isinstance(data, dict) else ""
valid = (
    isinstance(data, dict)
    and data.get("name") == release
    and data.get("namespace") == namespace
    and data.get("chart") == chart
    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{{0,127}}", version) is not None
    and (not expected_version or version == expected_version)
    and str(data.get("status") or "").lower() == "deployed"
)
if not valid:
    raise SystemExit(1)
print(version)
' "${{RELEASE}}" "${{NAMESPACE}}" "${{CHART_NAME}}" "${{CHART_VERSION}}" 2>/dev/null)"; then
    echo 'ERROR: Existing collector Helm release is unavailable or not deployed; command output suppressed.' >&2
    exit 1
fi
if [[ -z "${{CHART_VERSION}}" ]]; then
    CHART_VERSION="${{CURRENT_CHART_VERSION}}"
fi

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "${{TMPDIR_LOCAL}}"' EXIT

secure_copy_token() {{
    local source_path="${{1:?source token file required}}"
    local destination_path="${{2:?destination token file required}}"
    local label="${{3:?token label required}}"
    python3 - "${{source_path}}" "${{destination_path}}" "${{label}}" "${{ALLOW_LOOSE_TOKEN_PERMS:-false}}" <<'PY'
import os
import stat
import sys

source, destination, label, allow_loose = sys.argv[1:]
maximum = 16 * 1024
try:
    before = os.lstat(source)
except OSError:
    raise SystemExit(f"ERROR: {{label}} must reference an existing credential file.")
if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
    raise SystemExit(f"ERROR: {{label}} must be a regular file, not a symbolic link.")
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
try:
    descriptor = os.open(source, flags)
except OSError:
    raise SystemExit(f"ERROR: {{label}} could not be opened securely.")
try:
    info = os.fstat(descriptor)
    raw = os.read(descriptor, maximum + 1)
    after = os.fstat(descriptor)
finally:
    os.close(descriptor)
if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
    raise SystemExit(f"ERROR: {{label}} changed while it was opened.")
if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
    raise SystemExit(f"ERROR: {{label}} must be a current-user-owned regular file with one hard link.")
if stat.S_IMODE(info.st_mode) != 0o600 and allow_loose != "true":
    raise SystemExit(f"ERROR: {{label}} must be mode 600.")
if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
    raise SystemExit(f"ERROR: {{label}} changed while it was read.")
if info.st_size <= 0 or info.st_size > maximum or len(raw) != info.st_size:
    raise SystemExit(f"ERROR: {{label}} has an invalid size.")
try:
    text = raw.decode("utf-8", "strict")
except UnicodeError:
    raise SystemExit(f"ERROR: {{label}} is not valid UTF-8 text.")
if text.endswith("\\r\\n"):
    token = text[:-2]
elif text.endswith("\\n"):
    token = text[:-1]
else:
    token = text
if not token or "\\x00" in token or any(character.isspace() for character in token):
    raise SystemExit(f"ERROR: {{label}} must contain one token with at most one trailing newline.")
payload = token.encode("utf-8")
out_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
output = os.open(destination, out_flags, 0o600)
try:
    view = memoryview(payload)
    while view:
        written = os.write(output, view)
        if written <= 0:
            raise SystemExit(f"ERROR: {{label}} could not be copied completely.")
        view = view[written:]
finally:
    os.close(output)
PY
}}

O11Y_TOKEN_COPY="${{TMPDIR_LOCAL}}/o11y-token"
secure_copy_token "${{O11Y_TOKEN_FILE}}" "${{O11Y_TOKEN_COPY}}" O11Y_TOKEN_FILE
HELM_SECRET_FLAGS=(--set-file "splunkObservability.accessToken=${{O11Y_TOKEN_COPY}}")
PLATFORM_FLAGS=()
if [[ -n "${{PLATFORM_HEC_TOKEN_FILE}}" ]]; then
    PLATFORM_HEC_TOKEN_COPY="${{TMPDIR_LOCAL}}/platform-hec-token"
    secure_copy_token "${{PLATFORM_HEC_TOKEN_FILE}}" "${{PLATFORM_HEC_TOKEN_COPY}}" PLATFORM_HEC_TOKEN_FILE
    HELM_SECRET_FLAGS+=(--set-file "splunkPlatform.token=${{PLATFORM_HEC_TOKEN_COPY}}")
fi
if [[ -n "${{PLATFORM_HEC_URL}}" ]]; then
    PLATFORM_FLAGS+=(--set-string "splunkPlatform.endpoint=${{PLATFORM_HEC_URL}}")
fi

"${{HELM[@]}}" get values "${{RELEASE}}" -n "${{NAMESPACE}}" -o yaml > "${{TMPDIR_LOCAL}}/current-values.yaml"

if [[ "${{PLATFORM_ENABLED}}" == "true" && "${{EXPORT_MODE}}" == "stdout" ]]; then
    echo 'ERROR: Stdout export cannot prove the required Splunk index/sourcetype path; use file mode for production apply.' >&2
    exit 1
fi
if [[ "${{PLATFORM_ENABLED}}" == "true" && "${{EXPORT_MODE}}" == "file" ]]; then
    if ! yq eval -e '.splunkPlatform.logsEnabled == true' "${{OVERLAY}}" >/dev/null; then
        echo 'ERROR: The rendered overlay does not enable Splunk Platform logs.' >&2
        exit 1
    fi
    OVERLAY_INDEX="$(yq eval -r '.logsCollection.extraFileLogs."filelog/tetragon".resource."com.splunk.index" // ""' "${{OVERLAY}}")"
    OVERLAY_SOURCETYPE="$(yq eval -r '.logsCollection.extraFileLogs."filelog/tetragon".resource."com.splunk.sourcetype" // ""' "${{OVERLAY}}")"
    if [[ "${{OVERLAY_INDEX}}" != "${{EXPECTED_PLATFORM_INDEX}}" || "${{OVERLAY_SOURCETYPE}}" != "${{EXPECTED_PLATFORM_SOURCETYPE}}" ]]; then
        echo 'ERROR: The rendered Splunk Platform index/sourcetype path is incomplete or drifted.' >&2
        exit 1
    fi

    RENDERED_HEC_URL="$(yq eval -r '.splunkPlatform.endpoint // ""' "${{OVERLAY}}")"
    INHERITED_HEC_URL="$(yq eval -r '.splunkPlatform.endpoint // ""' "${{TMPDIR_LOCAL}}/current-values.yaml")"
    INHERITED_HEC_TOKEN=false
    if yq eval -e '.splunkPlatform.token != null and .splunkPlatform.token != ""' "${{TMPDIR_LOCAL}}/current-values.yaml" >/dev/null; then
        INHERITED_HEC_TOKEN=true
    fi
    if [[ -n "${{PLATFORM_HEC_TOKEN_FILE}}" ]]; then
        if [[ -z "${{PLATFORM_HEC_URL}}" ]]; then
            echo 'ERROR: A provided PLATFORM_HEC_TOKEN_FILE requires PLATFORM_HEC_URL.' >&2
            exit 1
        fi
        if [[ -n "${{RENDERED_HEC_URL}}" && "${{PLATFORM_HEC_URL}}" != "${{RENDERED_HEC_URL}}" ]]; then
            echo 'ERROR: Runtime PLATFORM_HEC_URL differs from the reviewed rendered endpoint; re-render first.' >&2
            exit 1
        fi
        EFFECTIVE_HEC_URL="${{PLATFORM_HEC_URL}}"
    else
        if [[ "${{INHERITED_HEC_TOKEN}}" != "true" || -z "${{INHERITED_HEC_URL}}" ]]; then
            echo 'ERROR: Splunk Platform logs require a provided HEC URL/token file pair or a complete inherited release pair.' >&2
            exit 1
        fi
        if [[ -n "${{RENDERED_HEC_URL}}" && "${{RENDERED_HEC_URL}}" != "${{INHERITED_HEC_URL}}" ]]; then
            echo 'ERROR: Rendered and inherited HEC endpoints differ; provide a reviewed token file pair.' >&2
            exit 1
        fi
        EFFECTIVE_HEC_URL="${{INHERITED_HEC_URL}}"
    fi
    if ! python3 - "${{EFFECTIVE_HEC_URL}}" <<'PY'
import sys
from urllib.parse import urlsplit

parsed = urlsplit(sys.argv[1])
valid = (
    parsed.scheme == "https"
    and bool(parsed.hostname)
    and parsed.username is None
    and parsed.password is None
    and not parsed.query
    and not parsed.fragment
)
raise SystemExit(0 if valid else 1)
PY
    then
        echo 'ERROR: Effective Splunk Platform HEC endpoint is not a safe HTTPS URL.' >&2
        exit 1
    fi
fi

# shellcheck disable=SC2016  # yq expression, not a shell expansion
yq eval-all '. as $i ireduce ({{}}; . * $i)' "${{TMPDIR_LOCAL}}/current-values.yaml" "${{OVERLAY}}" > "${{TMPDIR_LOCAL}}/merged.yaml"
if "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" get configmap "${{RELEASE}}-obi" >/dev/null 2>&1; then
    "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" get configmap "${{RELEASE}}-obi" -o jsonpath='{{.data.ebpf-instrument-config\\.yml}}' > "${{TMPDIR_LOCAL}}/obi-config.yaml"
    if [[ -s "${{TMPDIR_LOCAL}}/obi-config.yaml" ]]; then
        OBI_CONFIG_FILE="${{TMPDIR_LOCAL}}/obi-config.yaml" yq eval '.obi.config.data = load(strenv(OBI_CONFIG_FILE))' -i "${{TMPDIR_LOCAL}}/merged.yaml"
    fi
fi
if "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" get configmap "${{RELEASE}}-otel-collector" >/dev/null 2>&1; then
    "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" get configmap "${{RELEASE}}-otel-collector" -o jsonpath='{{.data.relay}}' > "${{TMPDIR_LOCAL}}/gateway-relay.yaml"
    if [[ -s "${{TMPDIR_LOCAL}}/gateway-relay.yaml" ]]; then
        GATEWAY_CONFIG_FILE="${{TMPDIR_LOCAL}}/gateway-relay.yaml" yq eval '.gateway.config = load(strenv(GATEWAY_CONFIG_FILE))' -i "${{TMPDIR_LOCAL}}/merged.yaml"
    fi
fi
if [[ "${{NORMALIZE_OTLPHTTP}}" == "auto" ]]; then
    case "${{CHART_VERSION}}" in
        0.150.*|0.15[1-9].*|0.[2-9]*|[1-9]*) NORMALIZE_OTLPHTTP="true" ;;
        *) NORMALIZE_OTLPHTTP="false" ;;
    esac
fi
if [[ "${{NORMALIZE_OTLPHTTP}}" == "true" ]]; then
    yq eval '
      (.. | select(tag == "!!map")) |= with_entries(.key |= sub("^otlphttp"; "otlp_http")) |
      (.. | select(tag == "!!str")) |= sub("^otlphttp"; "otlp_http")
    ' "${{TMPDIR_LOCAL}}/merged.yaml" > "${{TMPDIR_LOCAL}}/merged.normalized.yaml"
    mv "${{TMPDIR_LOCAL}}/merged.normalized.yaml" "${{TMPDIR_LOCAL}}/merged.yaml"
fi

DRY_RUN_FLAG=()
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" == "true" ]]; then
    DRY_RUN_FLAG=(--dry-run --hide-secret)
    echo "DRY-RUN MODE: passing --dry-run --hide-secret to helm"
fi
VERSION_FLAG=()
if [[ -n "${{CHART_VERSION}}" ]]; then
    VERSION_FLAG=(--version "${{CHART_VERSION}}")
fi

"${{HELM[@]}}" upgrade "${{RELEASE}}" "${{CHART_REF}}" \\
    --namespace "${{NAMESPACE}}" \\
    "${{VERSION_FLAG[@]}}" \\
    --values "${{TMPDIR_LOCAL}}/merged.yaml" \\
    "${{HELM_SECRET_FLAGS[@]}}" \\
    "${{PLATFORM_FLAGS[@]}}" \\
    --force-conflicts \\
    --atomic \\
    --timeout 5m \\
    "${{DRY_RUN_FLAG[@]}}"

if [[ "${{K8S_APPLY_DRY_RUN:-false}}" != "true" ]]; then
    "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" rollout status daemonset/${{RELEASE}}-agent --timeout=180s
    if "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" get deployment/${{RELEASE}}-k8s-cluster-receiver >/dev/null 2>&1; then
        "${{KUBECTL[@]}}" -n "${{NAMESPACE}}" rollout status deployment/${{RELEASE}}-k8s-cluster-receiver --timeout=180s
    else
        echo "INFO: optional k8s-cluster-receiver deployment is not present; agent rollout is healthy."
    fi
fi
"""


def render_handoffs(
    args: argparse.Namespace,
    spec: dict[str, Any],
    realm: str,
    cluster_name: str,
    distribution: str,
) -> dict[str, str]:
    handoffs = spec.get("handoffs") or {}
    helpers: dict[str, str] = {}

    if handoffs.get("base_collector", True):
        helpers["handoff-base-collector.sh"] = f"""#!/usr/bin/env bash
set -euo pipefail

# Render the base Splunk OTel collector values, then merge our overlay.
# Requires yq (https://github.com/mikefarah/yq) for the deep-merge step.
if ! command -v yq >/dev/null 2>&1; then
    echo 'ERROR: yq required for overlay merge (https://github.com/mikefarah/yq).' >&2
    exit 1
fi

OVERLAY="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/splunk-otel-overlay/values.overlay.yaml"
BASE_OUTPUT_DIR="${{BASE_OUTPUT_DIR:-/tmp/splunk-observability-otel-rendered}}"

echo "Step 1: Render the base Splunk OTel collector values."
echo "  Run:"
echo "    bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \\\\"
echo "      --render-k8s --realm {realm} \\\\"
echo "      --cluster-name {cluster_name} --distribution {distribution} \\\\"
echo "      --output-dir ${{BASE_OUTPUT_DIR}}"
echo
echo "Step 2: Merge this skill's overlay into the base values."
echo "  Run:"
echo "    yq eval-all '. as \\$item ireduce ({{}}; . * \\$item)' \\\\"
echo "      ${{BASE_OUTPUT_DIR}}/k8s/values.yaml \\\\"
echo "      ${{OVERLAY}} \\\\"
echo "      > /tmp/merged-values.yaml"
echo
echo "Step 3: Apply the merged values via helm (token via --set-file --reuse-values)."
echo "  Run:"
echo "    helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \\\\"
echo "      -n splunk-otel --create-namespace --reuse-values \\\\"
echo "      -f /tmp/merged-values.yaml \\\\"
# shellcheck disable=SC2016  # printed instruction intentionally keeps the variable literal
echo '      --set-file splunkObservability.accessToken="$O11Y_TOKEN_FILE"'
"""

    if handoffs.get("hec_service", True) or bool_flag(args.render_platform_hec_helper):
        # splunk-hec-service-setup uses --token-name (not --hec-token-name) per
        # its setup.sh. Pin the platform to enterprise|cloud as required by
        # that skill's --platform flag.
        index = (spec.get("splunk_platform") or {}).get("index", "cisco_isovalent")
        helpers["handoff-hec-token.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Provision a Splunk Platform HEC token via splunk-hec-service-setup.\n"
            "# Set PLATFORM=enterprise or PLATFORM=cloud before running.\n"
            'PLATFORM="${PLATFORM:-enterprise}"\n'
            'echo "Run:"\n'
            'echo "  bash skills/splunk-hec-service-setup/scripts/setup.sh \\\\"\n'
            'echo "    --platform ${PLATFORM} --phase render \\\\"\n'
            'echo "    --token-name isovalent_tetragon \\\\"\n'
            f'echo "    --default-index {index} \\\\"\n'
            f'echo "    --allowed-indexes {index}"\n'
            "echo\n"
            'echo "Then run apply-isovalent-overlay.sh with PLATFORM_HEC_URL and"\n'
            'echo "PLATFORM_HEC_TOKEN_FILE set to the provisioned endpoint and token file."\n'
        )

    if handoffs.get("cisco_security_cloud", True):
        # cisco-security-cloud-setup uses configure_input.sh (not --product flag).
        # The Isovalent Runtime Security input type is sbg_isovalent_input per
        # skills/cisco-security-cloud-setup/products.json lines 200-219.
        helpers["handoff-cisco-security-cloud.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Configure the Splunk Platform Cisco Security Cloud App input for\n"
            "# Isovalent Runtime Security (sourcetype cisco:isovalent:processExec,\n"
            "# index cisco_isovalent). The app provides field aliases on the\n"
            "# specific sourcetype for Splunk Threat Research Team detections.\n"
            'echo "Step 1: Install the Cisco Security Cloud App if not already installed:"\n'
            'echo "  bash skills/cisco-security-cloud-setup/scripts/setup.sh --install"\n'
            "echo\n"
            'echo "Step 2: Configure the Isovalent Runtime Security input:"\n'
            'echo "  bash skills/cisco-security-cloud-setup/scripts/configure_input.sh \\\\"\n'
            'echo "    --input-type sbg_isovalent_input \\\\"\n'
            'echo "    --name Isovalent_Default \\\\"\n'
            'echo "    --set index cisco_isovalent \\\\"\n'
            'echo "    --set interval 300"\n'
            "echo\n"
            'echo "(Optional) For the edge-processor variant, repeat with --input-type sbg_isovalent_edge_processor_input."\n'
        )

    if handoffs.get("dashboard_builder", True):
        # splunk-observability-dashboard-builder uses --spec (not --import-json)
        # per its setup.sh lines 35-39 + 76-79.
        helpers["handoff-dashboards.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Import the bundled token-scrubbed dashboards via splunk-observability-dashboard-builder.\n"
            'DASHBOARDS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/dashboards"\n'
            'echo "Run for each dashboard JSON in ${DASHBOARDS_DIR}:"\n'
            'echo "  for spec in ${DASHBOARDS_DIR}/*.json; do"\n'
            'echo "    bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \\\\"\n'
            'echo "      --render --apply --realm \\$REALM \\\\"\n'
            'echo "      --spec \\$spec \\\\"\n'
            'echo "      --token-file \\$O11Y_API_TOKEN_FILE"\n'
            'echo "  done"\n'
        )

    if handoffs.get("native_ops", True):
        helpers["handoff-detectors.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Apply starter detectors via splunk-observability-native-ops.\n"
            'DETECTORS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/detectors"\n'
            'echo "Run for each detector spec in ${DETECTORS_DIR}:"\n'
            'echo "  for spec in ${DETECTORS_DIR}/*.yaml; do"\n'
            'echo "    bash skills/splunk-observability-native-ops/scripts/setup.sh \\\\"\n'
            'echo "      --render --apply --realm \\$REALM \\\\"\n'
            'echo "      --spec \\$spec \\\\"\n'
            'echo "      --token-file \\$O11Y_API_TOKEN_FILE"\n'
            'echo "  done"\n'
        )

    return helpers


def render_detectors(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = spec.get("detectors") or {}
    if not block.get("enabled", True):
        return {}
    thresholds = block.get("thresholds") or {}
    detectors = {
        "cilium-drop-rate": {
            "test_type": "isovalent",
            "detectors": [
                {
                    "name": "Cilium drop rate",
                    "metric": "hubble_drop_total",
                    "direction": "above",
                    "threshold": thresholds.get("cilium_drop_rate_per_s", 100),
                    "severity": "Major",
                    "aggregation": "rate",
                }
            ],
        },
        "hubble-dns-failures": {
            "test_type": "isovalent",
            "detectors": [
                {
                    "name": "Hubble DNS failure rate",
                    "metric": "hubble_dns_responses_total",
                    "direction": "above",
                    "threshold": thresholds.get("hubble_dns_failure_rate", 0.05),
                    "severity": "Warning",
                    "aggregation": "ratio",
                }
            ],
        },
        "tetragon-event-rate": {
            "test_type": "isovalent",
            "detectors": [
                {
                    "name": "Tetragon event rate",
                    "metric": "tetragon_events_total",
                    "direction": "above",
                    "threshold": thresholds.get("tetragon_event_rate_per_s", 1000),
                    "severity": "Info",
                    "aggregation": "rate",
                }
            ],
        },
    }
    return detectors


def render_metadata(
    args: argparse.Namespace, spec: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    splunk_block = spec.get("splunk_platform") or {}
    collector = spec.get("collector") or {}
    collector_chart_ref = collector.get(
        "chart_ref", "splunk-otel-collector-chart/splunk-otel-collector"
    )
    return {
        "skill": SKILL_NAME,
        "realm": config["realm"],
        "cluster_name": config["cluster_name"],
        "distribution": config["distribution"],
        "export_mode": config["export_mode"],
        "legacy_fluentd_hec": config["legacy_fluentd"],
        "splunk_platform_enabled": splunk_block.get("enabled", True),
        "splunk_platform_index": splunk_block.get("index", "cisco_isovalent"),
        "splunk_platform_sourcetype": splunk_block.get("sourcetype", "cisco:isovalent"),
        "splunk_platform_hec_url": config["hec_url"],
        "platform_hec_token_configured": bool(config["platform_hec_token_file"]),
        "render_platform_hec_helper": config["render_hec_helper"],
        "collector": {
            "release": collector.get("release", "splunk-otel-collector"),
            "namespace": collector.get("namespace", ""),
            "chart_ref": collector_chart_ref,
            "chart_name": collector_chart_ref.rsplit("/", 1)[-1],
            "chart_version": collector.get("chart_version", ""),
        },
        "scrape_jobs": effective_scrape_jobs(spec),
        "signalflow_metrics": representative_signalflow_metrics(spec),
        "warnings": warnings(args, spec),
    }


def warnings(args: argparse.Namespace, spec: dict[str, Any]) -> list[str]:
    items: list[str] = []
    spec_export_mode = (spec.get("tetragon_export") or {}).get("mode", "file")
    if (
        bool_flag(args.legacy_fluentd_hec)
        or args.export_mode == "fluentd"
        or (not args.export_mode and spec_export_mode == "fluentd")
    ):
        items.append(
            "DEPRECATED: --legacy-fluentd-hec uses fluent-plugin-splunk-hec which "
            "was archived 2025-06-24. Plan to migrate to the file-based path "
            "(default --export-mode file)."
        )
    distribution = args.distribution or spec.get("distribution", "")
    if distribution == "openshift":
        items.append(
            "OpenShift detected: the overlay enables kubeletstats.insecure_skip_verify=true "
            "(required for kubelet self-signed certs) and disables certmanager."
        )
    return items


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=__import__("sys").stderr)
        return 1
    try:
        spec = load_spec(spec_path)
        config = normalize_configuration(args, spec)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1

    realm = config["realm"]
    cluster_name = config["cluster_name"]
    distribution = config["distribution"]
    export_mode = config["export_mode"]
    legacy_fluentd = config["legacy_fluentd"]

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "export_mode": export_mode,
        "legacy_fluentd_hec": legacy_fluentd,
        "warnings": warnings(args, spec),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Splunk Observability Isovalent Integration render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    if out.is_symlink():
        print("ERROR: --output-dir must not be a symbolic link.", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    if not out.is_dir():
        print("ERROR: --output-dir must be a directory.", file=sys.stderr)
        return 1
    # Remove only this renderer's managed artifacts so changed specs cannot
    # leave stale helpers, dashboards, detectors, or output settings behind.
    for relative in (
        "splunk-otel-overlay",
        "dashboards",
        "detectors",
        "scripts",
        "metadata.json",
    ):
        managed = out / relative
        if managed.is_symlink():
            print(
                "ERROR: Managed output paths must not be symbolic links.",
                file=sys.stderr,
            )
            return 1
        if managed.is_dir():
            shutil.rmtree(managed)
        elif managed.exists():
            managed.unlink()

    overlay = overlay_values(
        spec,
        cluster_name=cluster_name,
        distribution=distribution,
        export_mode=export_mode,
        legacy_fluentd=legacy_fluentd,
        platform_hec_url=config["hec_url"],
    )
    write_yaml(out / "splunk-otel-overlay/values.overlay.yaml", overlay)

    write_text(out / "scripts/scrub-tokens.py", SCRUB_TOKEN_PY, executable=True)

    # Dashboards: copy + scrub when --dashboards-source is provided. Otherwise
    # write a placeholder README explaining how to drop in the upstream JSONs.
    dashboards_block = spec.get("dashboards") or {}
    source_dir = args.dashboards_source or dashboards_block.get("source_dir", "")
    dashboards_out = out / "dashboards"
    if dashboards_block.get("enabled", True) and source_dir:
        src = Path(source_dir)
        if not src.is_dir():
            print(
                f"ERROR: --dashboards-source {source_dir} is not a directory.",
                file=__import__("sys").stderr,
            )
            return 1
        for json_file in sorted(src.glob("*.json")):
            target = dashboards_out / json_file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            # Use the rendered scrub-tokens.py script so the same logic that
            # validate.sh exercises also runs at render time.
            scrubber = out / "scripts" / "scrub-tokens.py"
            import subprocess

            result = subprocess.run(
                ["python3", str(scrubber), str(json_file), str(target)],
                check=False,
            )
            if result.returncode != 0:
                print(
                    f"ERROR: scrub-tokens refused {json_file}; remove the inline tokens before re-rendering.",
                    file=__import__("sys").stderr,
                )
                return 1
    elif dashboards_block.get("enabled", True):
        write_text(
            dashboards_out / "README.md",
            "# Dashboards\n\n"
            "Drop the upstream Cilium / Hubble dashboard JSON exports into this directory\n"
            "(or re-run the renderer with --dashboards-source <dir>) and they will be\n"
            "token-scrubbed via scripts/scrub-tokens.py.\n\n"
            "Reference dashboards are available at\n"
            "/Users/alecchamberlain/Documents/GitHub/Isovalent_Splunk_o11y/examples/*.json.\n"
            "Do NOT copy from values/*.yaml in that repo -- those files have been observed\n"
            "to contain plaintext access tokens.\n",
        )

    detectors = render_detectors(spec)
    for name, payload in detectors.items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    helpers = render_handoffs(args, spec, realm, cluster_name, distribution)
    for name, body in helpers.items():
        write_text(out / f"scripts/{name}", body, executable=True)

    write_text(
        out / "scripts/apply-isovalent-overlay.sh",
        render_apply_overlay_script(
            spec,
            o11y_token_file=config["o11y_token_file"],
            platform_hec_token_file=config["platform_hec_token_file"],
            platform_hec_url=config["hec_url"],
            export_mode=config["export_mode"],
        ),
        executable=True,
    )

    write_json(out / "metadata.json", render_metadata(args, spec, config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
