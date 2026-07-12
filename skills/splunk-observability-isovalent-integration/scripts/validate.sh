#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)" || {
        log "ERROR: python3 is required for validation."
        exit 1
    }
fi

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-isovalent-rendered"
LIVE=false
SIGNALFLOW=false
SPLUNK_SEARCH=false
PRODUCTION=false
KUBE_CONTEXT=""
ALLOW_CURRENT_CONTEXT=false
CILIUM_NAMESPACE="kube-system"
TETRAGON_NAMESPACE="tetragon"
COLLECTOR_RELEASE=""
COLLECTOR_NAMESPACE=""
O11Y_TOKEN_FILE=""
SPLUNK_MANAGEMENT_URL=""
SPLUNK_SEARCH_TOKEN_FILE=""
API_LOOKBACK_SECONDS="600"
API_TIMEOUT_SECONDS="20"
ALLOW_LOOSE_TOKEN_PERMS=false

usage() {
    cat <<'EOF'
Splunk Observability Isovalent Integration validation

Usage:
  bash skills/splunk-observability-isovalent-integration/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --kube-context CTX Kubernetes context for live checks
  --allow-current-context
                     Explicitly acknowledge the current context for --live
  --cilium-namespace NS
                     Namespace for Cilium pods (default: kube-system)
  --tetragon-namespace NS
                     Namespace for Tetragon pods (default: tetragon)
  --collector-release NAME
                     Helm release override; must match rendered metadata
  --collector-namespace NS
                     Namespace override; must match rendered metadata
  --live             Require Helm health, collector readiness, and every rendered
                     pod metrics endpoint. Also runs configured API probes.
  --signalflow       Require current cilium/hubble/tetragon series in Observability
  --o11y-token-file PATH
                     Observability API token file (regular, one hard link, mode 600)
  --splunk-search    Require current index/sourcetype events through Splunk REST
  --production       Require --live, --signalflow, and --splunk-search together;
                     this is the full production acceptance gate
  --splunk-url URL   Splunk management URL for --splunk-search (https only)
  --splunk-search-token-file PATH
                     Splunk bearer-token file (regular, one hard link, mode 600)
  --api-lookback-seconds N
                     API probe lookback (default: 600)
  --api-timeout-seconds N
                     Per-request timeout (default: 20)
  --allow-loose-token-perms
                     Permit non-600 token mode; symlinks, hard links, and wrong
                     ownership are still rejected
  --help             Show this help

Direct token flags are rejected. Credentials must be file-backed.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
        --cilium-namespace) require_arg "$1" "$#" || exit 1; CILIUM_NAMESPACE="$2"; shift 2 ;;
        --tetragon-namespace) require_arg "$1" "$#" || exit 1; TETRAGON_NAMESPACE="$2"; shift 2 ;;
        --collector-release) require_arg "$1" "$#" || exit 1; COLLECTOR_RELEASE="$2"; shift 2 ;;
        --collector-namespace) require_arg "$1" "$#" || exit 1; COLLECTOR_NAMESPACE="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --signalflow) SIGNALFLOW=true; shift ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --splunk-search) SPLUNK_SEARCH=true; shift ;;
        --production) PRODUCTION=true; shift ;;
        --splunk-url) require_arg "$1" "$#" || exit 1; SPLUNK_MANAGEMENT_URL="$2"; shift 2 ;;
        --splunk-search-token-file) require_arg "$1" "$#" || exit 1; SPLUNK_SEARCH_TOKEN_FILE="$2"; shift 2 ;;
        --api-lookback-seconds) require_arg "$1" "$#" || exit 1; API_LOOKBACK_SECONDS="$2"; shift 2 ;;
        --api-timeout-seconds) require_arg "$1" "$#" || exit 1; API_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "--o11y-token-file"
            exit 1
            ;;
        --access-token=*|--token=*|--bearer-token=*|--api-token=*|--o11y-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "--o11y-token-file"
            exit 1
            ;;
        --splunk-search-token|--splunk-token)
            reject_secret_arg "$1" "--splunk-search-token-file"
            exit 1
            ;;
        --splunk-search-token=*|--splunk-token=*)
            reject_secret_arg "${1%%=*}" "--splunk-search-token-file"
            exit 1
            ;;
        --platform-hec-token|--hec-token)
            reject_secret_arg "$1" "--platform-hec-token-file"
            exit 1
            ;;
        --platform-hec-token=*|--hec-token=*)
            reject_secret_arg "${1%%=*}" "--platform-hec-token-file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "${O11Y_TOKEN_FILE}" && "${SIGNALFLOW}" == "true" ]]; then
    O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
fi

if [[ "${PRODUCTION}" == "true" && (
    "${LIVE}" != "true" || "${SIGNALFLOW}" != "true" || "${SPLUNK_SEARCH}" != "true"
) ]]; then
    log "ERROR: --production requires --live, --signalflow, and --splunk-search."
    exit 1
fi

if ! [[ "${API_LOOKBACK_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    log "ERROR: --api-lookback-seconds must be a positive integer."
    exit 1
fi
if [[ "${LIVE}" == "true" ]]; then
    if [[ -z "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" != "true" ]]; then
        log "ERROR: --live requires --kube-context or explicit --allow-current-context acknowledgement."
        exit 1
    fi
    if [[ -n "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
        log "ERROR: Use either --kube-context or --allow-current-context, not both."
        exit 1
    fi
elif [[ "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
    log "ERROR: --allow-current-context is valid only with --live."
    exit 1
fi
if ! [[ "${API_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]] || (( API_TIMEOUT_SECONDS > 120 )); then
    log "ERROR: --api-timeout-seconds must be an integer from 1 through 120."
    exit 1
fi
if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_token_file() {
    local path="$1" label="$2"
    python3 - "${path}" "${label}" "${ALLOW_LOOSE_TOKEN_PERMS}" <<'PY'
import os
import stat
import sys

path, label, allow_loose = sys.argv[1:]
try:
    info = os.lstat(path)
except OSError:
    raise SystemExit(f"ERROR: {label} must reference an existing credential file.")
if stat.S_ISLNK(info.st_mode):
    raise SystemExit(f"ERROR: {label} must not be a symbolic link.")
if not stat.S_ISREG(info.st_mode):
    raise SystemExit(f"ERROR: {label} must reference a regular file.")
if info.st_uid != os.geteuid():
    raise SystemExit(f"ERROR: {label} must be owned by the current user.")
if info.st_nlink != 1:
    raise SystemExit(f"ERROR: {label} must have exactly one hard link.")
if stat.S_IMODE(info.st_mode) != 0o600 and allow_loose != "true":
    raise SystemExit(f"ERROR: {label} must be mode 600.")
if info.st_size <= 0 or info.st_size > 16 * 1024:
    raise SystemExit(f"ERROR: {label} has an invalid size.")
PY
}

if [[ -n "${O11Y_TOKEN_FILE}" ]]; then
    check_token_file "${O11Y_TOKEN_FILE}" "--o11y-token-file"
fi
if [[ -n "${SPLUNK_SEARCH_TOKEN_FILE}" ]]; then
    check_token_file "${SPLUNK_SEARCH_TOKEN_FILE}" "--splunk-search-token-file"
fi
if [[ "${LIVE}" == "true" && -n "${O11Y_TOKEN_FILE}" ]]; then
    SIGNALFLOW=true
fi
if [[ -n "${SPLUNK_MANAGEMENT_URL}" && -n "${SPLUNK_SEARCH_TOKEN_FILE}" ]]; then
    SPLUNK_SEARCH=true
fi
if [[ "${SIGNALFLOW}" == "true" && -z "${O11Y_TOKEN_FILE}" ]]; then
    log "ERROR: --signalflow requires --o11y-token-file or SPLUNK_O11Y_TOKEN_FILE."
    exit 1
fi
if [[ "${SPLUNK_SEARCH}" == "true" && ( -z "${SPLUNK_MANAGEMENT_URL}" || -z "${SPLUNK_SEARCH_TOKEN_FILE}" ) ]]; then
    log "ERROR: --splunk-search requires --splunk-url and --splunk-search-token-file."
    exit 1
fi
if [[ -n "${SPLUNK_MANAGEMENT_URL}" || -n "${SPLUNK_SEARCH_TOKEN_FILE}" ]]; then
    if [[ -z "${SPLUNK_MANAGEMENT_URL}" || -z "${SPLUNK_SEARCH_TOKEN_FILE}" ]]; then
        log "ERROR: Splunk search URL and token file must be supplied together."
        exit 1
    fi
fi

PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" \
python3 - "${OUTPUT_DIR}" <<'PY'
from __future__ import annotations

import json
import os
import re
import stat
import sys
import urllib.parse
from pathlib import Path

from yaml_compat import load_yaml_or_json

out = Path(sys.argv[1])
metadata_path = out / "metadata.json"
overlay_path = out / "splunk-otel-overlay" / "values.overlay.yaml"
for required in (metadata_path, overlay_path):
    if not required.is_file():
        raise SystemExit(f"ERROR: Missing required rendered file: {required}")
    if required.is_symlink():
        raise SystemExit("ERROR: Required rendered files must not be symbolic links.")

for path in out.rglob("*"):
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise SystemExit("ERROR: Could not safely inspect the rendered output tree.") from exc
    if stat.S_ISLNK(mode):
        raise SystemExit("ERROR: Rendered output must not contain symbolic links.")

try:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit("ERROR: metadata.json is not valid JSON.") from exc
if not isinstance(metadata, dict):
    raise SystemExit("ERROR: metadata.json must contain an object.")
if metadata.get("skill") != "splunk-observability-isovalent-integration":
    raise SystemExit("ERROR: metadata.json belongs to a different skill.")
if metadata.get("realm") not in {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}:
    raise SystemExit("ERROR: metadata.json contains an unsupported Observability realm.")
if metadata.get("distribution") not in {"openshift", "kubernetes", "eks", "gke"}:
    raise SystemExit("ERROR: metadata.json contains an unsupported Kubernetes distribution.")
cluster_name = metadata.get("cluster_name")
if not isinstance(cluster_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}", cluster_name):
    raise SystemExit("ERROR: metadata.json contains an invalid cluster name.")
export_mode = metadata.get("export_mode")
if export_mode not in {"file", "stdout", "fluentd"}:
    raise SystemExit("ERROR: metadata.json contains an unsupported export mode.")
collector_contract = metadata.get("collector")
if not isinstance(collector_contract, dict) or set(collector_contract) != {
    "release", "namespace", "chart_ref", "chart_name", "chart_version"
}:
    raise SystemExit("ERROR: metadata.json has an invalid collector identity contract.")
if not isinstance(collector_contract["release"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", collector_contract["release"]):
    raise SystemExit("ERROR: metadata.json has an invalid collector release.")
if not isinstance(collector_contract["namespace"], str) or (
    collector_contract["namespace"] and not re.fullmatch(r"[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?", collector_contract["namespace"])
):
    raise SystemExit("ERROR: metadata.json has an invalid collector namespace.")
if not isinstance(collector_contract["chart_ref"], str) or not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", collector_contract["chart_ref"]):
    raise SystemExit("ERROR: metadata.json has an invalid collector chart reference.")
if collector_contract["chart_name"] != collector_contract["chart_ref"].rsplit("/", 1)[-1]:
    raise SystemExit("ERROR: metadata.json collector chart identity is inconsistent.")
if not isinstance(collector_contract["chart_version"], str) or (
    collector_contract["chart_version"] and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", collector_contract["chart_version"])
):
    raise SystemExit("ERROR: metadata.json has an invalid collector chart version.")

index = metadata.get("splunk_platform_index")
sourcetype = metadata.get("splunk_platform_sourcetype")
if not isinstance(index, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", index):
    raise SystemExit("ERROR: metadata.json contains an invalid Splunk index.")
if not isinstance(sourcetype, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:.-]{0,255}", sourcetype):
    raise SystemExit("ERROR: metadata.json contains an invalid Splunk sourcetype.")

try:
    overlay = load_yaml_or_json(
        overlay_path.read_text(encoding="utf-8"), source=str(overlay_path)
    )
except Exception as exc:
    raise SystemExit("ERROR: values.overlay.yaml is not valid YAML.") from exc
if not isinstance(overlay, dict):
    raise SystemExit("ERROR: values.overlay.yaml must contain a mapping.")

agent = overlay.get("agent")
if not isinstance(agent, dict):
    raise SystemExit("ERROR: Overlay is missing agent configuration.")
config = agent.get("config")
if not isinstance(config, dict):
    raise SystemExit("ERROR: Overlay is missing agent.config.")
receivers = config.get("receivers")
if not isinstance(receivers, dict):
    raise SystemExit("ERROR: Overlay is missing agent.config.receivers.")
expected_jobs = metadata.get("scrape_jobs")
if not isinstance(expected_jobs, list) or not expected_jobs or not all(
    isinstance(item, str) and item.startswith("prometheus/isovalent_")
    for item in expected_jobs
):
    raise SystemExit("ERROR: metadata.json has an invalid scrape_jobs contract.")
if len(expected_jobs) != len(set(expected_jobs)):
    raise SystemExit("ERROR: metadata.json repeats a scrape job.")
actual_jobs = sorted(key for key in receivers if key.startswith("prometheus/isovalent_"))
if actual_jobs != sorted(set(expected_jobs)):
    raise SystemExit("ERROR: Overlay Prometheus receivers do not match metadata.scrape_jobs.")
signalflow_metrics = metadata.get("signalflow_metrics")
if not isinstance(signalflow_metrics, dict) or set(signalflow_metrics) != {"cilium", "hubble", "tetragon"}:
    raise SystemExit("ERROR: metadata.json has an invalid SignalFlow metric contract.")
for family, metric in signalflow_metrics.items():
    if not isinstance(metric, str) or not re.fullmatch(rf"{family}_[A-Za-z0-9_.:/-]{{1,511}}", metric):
        raise SystemExit("ERROR: metadata.json has an invalid representative SignalFlow metric.")
for receiver_name in actual_jobs:
    receiver = receivers.get(receiver_name)
    scrape_configs = (receiver or {}).get("config", {}).get("scrape_configs")
    if not isinstance(scrape_configs, list) or len(scrape_configs) != 1:
        raise SystemExit("ERROR: An Isovalent receiver has an invalid scrape configuration.")
    scrape = scrape_configs[0]
    if scrape.get("metrics_path") != "/metrics" or scrape.get("kubernetes_sd_configs") != [{"role": "pod"}]:
        raise SystemExit("ERROR: An Isovalent receiver is not configured for pod metrics discovery.")

processors = config.get("processors")
include = (processors or {}).get("filter/includemetrics", {}).get("metrics", {}).get("include", {})
metric_names = include.get("metric_names")
if include.get("match_type") != "strict" or not isinstance(metric_names, list) or not metric_names or not all(isinstance(item, str) for item in metric_names):
    raise SystemExit("ERROR: Overlay is missing the strict filter/includemetrics allow-list.")
if not set(signalflow_metrics.values()).issubset(set(metric_names)):
    raise SystemExit("ERROR: Representative SignalFlow metrics are absent from the allow-list.")
metrics_pipeline = config.get("service", {}).get("pipelines", {}).get("metrics", {})
if sorted(set(actual_jobs) - set(metrics_pipeline.get("receivers") or [])):
    raise SystemExit("ERROR: A rendered Isovalent receiver is absent from the metrics pipeline.")
if "filter/includemetrics" not in (metrics_pipeline.get("processors") or []):
    raise SystemExit("ERROR: The metrics pipeline does not use filter/includemetrics.")

platform_enabled = metadata.get("splunk_platform_enabled")
if not isinstance(platform_enabled, bool):
    raise SystemExit("ERROR: metadata.json has an invalid splunk_platform_enabled value.")
splunk_platform = overlay.get("splunkPlatform")
logs_collection = overlay.get("logsCollection")
hec_url = metadata.get("splunk_platform_hec_url")
if not isinstance(hec_url, str):
    raise SystemExit("ERROR: metadata.json has an invalid HEC URL contract.")
if hec_url:
    parsed_hec_url = urllib.parse.urlsplit(hec_url)
    if parsed_hec_url.scheme != "https" or not parsed_hec_url.hostname or parsed_hec_url.username is not None or parsed_hec_url.password is not None or parsed_hec_url.query or parsed_hec_url.fragment:
        raise SystemExit("ERROR: metadata.json contains an unsafe HEC URL.")
if not isinstance(metadata.get("platform_hec_token_configured"), bool):
    raise SystemExit("ERROR: metadata.json has an invalid HEC token configuration marker.")
if not isinstance(metadata.get("render_platform_hec_helper"), bool):
    raise SystemExit("ERROR: metadata.json has an invalid HEC helper marker.")
if metadata.get("platform_hec_token_configured") and not hec_url:
    raise SystemExit("ERROR: A configured HEC token is missing its HEC endpoint.")
if hec_url and (not isinstance(splunk_platform, dict) or splunk_platform.get("endpoint") != hec_url):
    raise SystemExit("ERROR: Overlay HEC endpoint does not match metadata.")

if platform_enabled and export_mode == "file":
    if not isinstance(splunk_platform, dict) or splunk_platform.get("logsEnabled") is not True:
        raise SystemExit("ERROR: File export requires splunkPlatform.logsEnabled: true.")
    receiver = (logs_collection or {}).get("extraFileLogs", {}).get("filelog/tetragon")
    if not isinstance(receiver, dict):
        raise SystemExit("ERROR: File export is missing logsCollection.extraFileLogs.filelog/tetragon.")
    resource = receiver.get("resource")
    if not isinstance(resource, dict):
        raise SystemExit("ERROR: Tetragon filelog receiver is missing resource attributes.")
    if resource.get("com.splunk.index") != index:
        raise SystemExit("ERROR: Tetragon filelog index does not match metadata.")
    if resource.get("com.splunk.sourcetype") != sourcetype:
        raise SystemExit("ERROR: Tetragon filelog sourcetype does not match metadata.")
    if resource.get("k8s.cluster.name") != cluster_name:
        raise SystemExit("ERROR: Tetragon filelog resource is not scoped to metadata.cluster_name.")
    volumes = agent.get("extraVolumes")
    mounts = agent.get("extraVolumeMounts")
    if not isinstance(volumes, list) or not isinstance(mounts, list):
        raise SystemExit("ERROR: File export is missing its hostPath volume and mount.")
    tetragon_volumes = [item for item in volumes if isinstance(item, dict) and item.get("name") == "tetragon"]
    tetragon_mounts = [item for item in mounts if isinstance(item, dict) and item.get("name") == "tetragon"]
    if len(tetragon_volumes) != 1 or len(tetragon_mounts) != 1:
        raise SystemExit("ERROR: File export must render exactly one Tetragon volume and mount.")
    host_path = (tetragon_volumes[0].get("hostPath") or {}).get("path")
    mount_path = tetragon_mounts[0].get("mountPath")
    includes = receiver.get("include")
    if not isinstance(host_path, str) or not host_path.startswith("/") or mount_path != host_path:
        raise SystemExit("ERROR: Tetragon hostPath and mountPath are not aligned.")
    if not isinstance(includes, list) or len(includes) != 1 or not isinstance(includes[0], str):
        raise SystemExit("ERROR: Tetragon filelog receiver must contain one include glob.")
    if not includes[0].startswith(host_path.rstrip("/") + "/"):
        raise SystemExit("ERROR: Tetragon filelog include glob is outside its hostPath.")
elif platform_enabled and export_mode == "stdout":
    if not isinstance(splunk_platform, dict) or splunk_platform.get("logsEnabled") is not True:
        raise SystemExit("ERROR: Stdout export requires splunkPlatform.logsEnabled: true.")
    if logs_collection is not None or agent.get("extraVolumes") or agent.get("extraVolumeMounts"):
        raise SystemExit("ERROR: Stdout export must not render the file-based hostPath path.")
elif platform_enabled and export_mode == "fluentd":
    if metadata.get("legacy_fluentd_hec") is not True:
        raise SystemExit("ERROR: Fluentd export must be explicitly marked as legacy.")
    if splunk_platform is not None or logs_collection is not None:
        raise SystemExit("ERROR: Legacy fluentd export must not enable the OTel Splunk Platform path.")
elif not platform_enabled:
    if splunk_platform is not None or logs_collection is not None:
        raise SystemExit("ERROR: Disabled Splunk Platform output rendered active log configuration.")

secret_patterns = (
    re.compile(
        r'''(?ix)
        ["\']?
        [A-Za-z0-9_.-]*(?:token|secret|authorization|bearer|password|credential|hec)[A-Za-z0-9_.-]*
        ["\']?\s*[:=]\s*["\']?
        (?!\$\{|<redacted>|/)[A-Za-z0-9._+/=-]{8,}
        '''
    ),
    re.compile(r'(?i)(?:authorization|x-sf-token)\s*[:=]\s*["\']?(?:bearer|splunk)?\s*(?!\$\{|<redacted>)[A-Za-z0-9._+/=-]{8,}'),
    re.compile(r'(?i)bearer\s+(?!\$\{|<redacted>)[A-Za-z0-9._+/=-]{8,}|splunk\s+(?!\$\{|<redacted>)[A-Za-z0-9._+/=-]{20,}'),
)
for path in out.rglob("*"):
    if not path.is_file():
        continue
    if path == out / "scripts" / "scrub-tokens.py":
        continue
    try:
        if path.stat().st_size > 5 * 1024 * 1024:
            raise SystemExit("ERROR: Rendered output contains an unexpectedly large file.")
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    except OSError as exc:
        raise SystemExit("ERROR: Could not safely scan a rendered file.") from exc
    if any(pattern.search(text) for pattern in secret_patterns):
        raise SystemExit("ERROR: A rendered file appears to contain inline credential material.")

dashboards = out / "dashboards"
if dashboards.is_dir():
    for path in dashboards.glob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit("ERROR: A rendered dashboard is not valid JSON.") from exc

for name in ("apply-isovalent-overlay.sh", "scrub-tokens.py"):
    path = out / "scripts" / name
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SystemExit(f"ERROR: Missing executable rendered helper: scripts/{name}")
PY

while IFS= read -r -d '' script; do
    if ! bash -n "${script}"; then
        log "ERROR: Rendered shell helper failed syntax validation."
        exit 1
    fi
done < <(find "${OUTPUT_DIR}/scripts" -maxdepth 1 -type f -name '*.sh' -print0)

log "Splunk Observability Isovalent Integration rendered assets passed static validation."

IFS='|' read -r METADATA_COLLECTOR_RELEASE METADATA_COLLECTOR_NAMESPACE \
    METADATA_COLLECTOR_CHART_NAME METADATA_COLLECTOR_CHART_VERSION < <(
    python3 - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json
import sys

collector = json.load(open(sys.argv[1], encoding="utf-8"))["collector"]
print("|".join((collector["release"], collector["namespace"], collector["chart_name"], collector["chart_version"])))
PY
)
if [[ -n "${COLLECTOR_RELEASE}" && "${COLLECTOR_RELEASE}" != "${METADATA_COLLECTOR_RELEASE}" ]]; then
    log "ERROR: --collector-release does not match rendered metadata."
    exit 1
fi
if [[ -n "${COLLECTOR_NAMESPACE}" && "${COLLECTOR_NAMESPACE}" != "${METADATA_COLLECTOR_NAMESPACE}" ]]; then
    log "ERROR: --collector-namespace does not match rendered metadata."
    exit 1
fi
COLLECTOR_RELEASE="${METADATA_COLLECTOR_RELEASE}"
COLLECTOR_NAMESPACE="${METADATA_COLLECTOR_NAMESPACE}"

if [[ "${LIVE}" == "true" ]]; then
    if [[ -z "${COLLECTOR_NAMESPACE}" || -z "${METADATA_COLLECTOR_CHART_VERSION}" ]]; then
        log "ERROR: --live requires exact collector.namespace and collector.chart_version in rendered metadata."
        exit 1
    fi
    log "  --live: requiring collector health and rendered pod metrics endpoints..."
    for tool in kubectl helm python3; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            log "ERROR: ${tool} is required for --live validation."
            exit 1
        fi
    done
    KUBECTL=(kubectl)
    HELM=(helm)
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        KUBECTL=(kubectl --context "${KUBE_CONTEXT}")
        HELM=(helm --kube-context "${KUBE_CONTEXT}")
    fi
    HELM_RELEASE_ROWS="$("${HELM[@]}" list --all-namespaces --filter "^${COLLECTOR_RELEASE}$" -o json 2>/dev/null)" || {
        log "ERROR: Helm release inventory failed."
        exit 1
    }
    if ! HELM_RELEASE_ROWS_JSON="${HELM_RELEASE_ROWS}" python3 - \
        "${COLLECTOR_RELEASE}" "${COLLECTOR_NAMESPACE}" <<'PY'
import json
import os
import sys

release, namespace = sys.argv[1:]
try:
    rows = json.loads(os.environ["HELM_RELEASE_ROWS_JSON"])
except (KeyError, json.JSONDecodeError):
    raise SystemExit("ERROR: Helm release inventory returned invalid JSON.")
if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
    raise SystemExit("ERROR: Helm release inventory is malformed.")
if any(row.get("name") != release for row in rows):
    raise SystemExit("ERROR: Helm release inventory included an unrelated release.")
if len(rows) != 1:
    raise SystemExit("ERROR: Expected exactly one collector Helm release.")
row = rows[0]
if row.get("namespace") != namespace:
    raise SystemExit("ERROR: Collector Helm namespace differs from rendered metadata.")
PY
    then
        exit 1
    fi

    # Helm list is an inventory snapshot. Stream the current, notes-free Helm
    # metadata document directly into one bounded parser so release identity,
    # exact chart version, and deployed state are verified atomically without
    # retaining customer-controlled Helm content in a shell variable.
    if ! "${HELM[@]}" get metadata "${COLLECTOR_RELEASE}" -n "${COLLECTOR_NAMESPACE}" -o json 2>/dev/null \
        | python3 -c '
import json
import sys

data = json.load(sys.stdin)
release, namespace, chart, version = sys.argv[1:]
valid = (
    isinstance(data, dict)
    and data.get("name") == release
    and data.get("namespace") == namespace
    and data.get("chart") == chart
    and str(data.get("version") or "") == version
    and str(data.get("status") or "").lower() == "deployed"
)
raise SystemExit(0 if valid else 1)
' "${COLLECTOR_RELEASE}" "${COLLECTOR_NAMESPACE}" "${METADATA_COLLECTOR_CHART_NAME}" "${METADATA_COLLECTOR_CHART_VERSION}" \
            >/dev/null 2>&1; then
        log "ERROR: Helm release ${COLLECTOR_RELEASE} is not a valid deployed release; command output suppressed."
        exit 1
    fi

    if ! "${KUBECTL[@]}" -n "${COLLECTOR_NAMESPACE}" get daemonset "${COLLECTOR_RELEASE}-agent" -o json 2>/dev/null \
        | python3 -c 'import json,sys; status=json.load(sys.stdin).get("status") or {}; desired=int(status.get("desiredNumberScheduled") or 0); ready=int(status.get("numberReady") or 0); raise SystemExit(0 if desired > 0 and ready == desired else 1)' \
            >/dev/null 2>&1; then
        log "ERROR: Collector agent DaemonSet is unavailable or not fully ready; command output suppressed."
        exit 1
    fi

    LIVE_VALIDATE_TMPDIR="$(mktemp -d)"
    trap 'rm -rf "${LIVE_VALIDATE_TMPDIR}"' EXIT
    if ! "${KUBECTL[@]}" -n "${COLLECTOR_NAMESPACE}" get configmap \
        "${COLLECTOR_RELEASE}-otel-agent" -o jsonpath='{.data.relay}' \
        > "${LIVE_VALIDATE_TMPDIR}/agent-relay.yaml" 2>/dev/null; then
        log "ERROR: Live collector agent relay ConfigMap is unavailable."
        exit 1
    fi
    if [[ ! -s "${LIVE_VALIDATE_TMPDIR}/agent-relay.yaml" ]]; then
        log "ERROR: Live collector agent relay is empty."
        exit 1
    fi
    PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" \
    "${PYTHON_BIN}" - "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml" \
        "${LIVE_VALIDATE_TMPDIR}/agent-relay.yaml" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

from yaml_compat import load_yaml_or_json


def load(path: str):
    data = load_yaml_or_json(Path(path).read_text(encoding="utf-8"), source=path)
    if not isinstance(data, dict):
        raise SystemExit("ERROR: Collector overlay/relay must contain a mapping.")
    return data


def mapping_subset(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and mapping_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return expected == actual
    return expected == actual


def ordered_subset(expected, actual) -> bool:
    if not isinstance(expected, list) or not isinstance(actual, list):
        return False
    iterator = iter(actual)
    return all(any(candidate == item for candidate in iterator) for item in expected)


try:
    overlay = load(sys.argv[1])
    relay = load(sys.argv[2])
except Exception:
    raise SystemExit("ERROR: Collector overlay/relay YAML could not be parsed.") from None
expected_config = (overlay.get("agent") or {}).get("config") or {}
live_receivers = relay.get("receivers") or {}
for name, receiver in (expected_config.get("receivers") or {}).items():
    if name.startswith("prometheus/isovalent_"):
        if live_receivers.get(name) != receiver:
            raise SystemExit("ERROR: Live Isovalent receiver/relabel/port configuration drifted.")
    elif name not in live_receivers or not mapping_subset(receiver, live_receivers[name]):
        raise SystemExit("ERROR: Live collector receiver configuration does not contain the rendered overlay.")

expected_processors = expected_config.get("processors") or {}
live_processors = relay.get("processors") or {}
for name, processor in expected_processors.items():
    if name == "filter/includemetrics":
        if live_processors.get(name) != processor:
            raise SystemExit("ERROR: Live metric allow-list processor drifted.")
    elif name not in live_processors or not mapping_subset(processor, live_processors[name]):
        raise SystemExit("ERROR: Live collector processors do not contain the rendered overlay.")

expected_pipeline = (((expected_config.get("service") or {}).get("pipelines") or {}).get("metrics") or {})
live_pipeline = (((relay.get("service") or {}).get("pipelines") or {}).get("metrics") or {})
for field in ("receivers", "processors", "exporters"):
    if not ordered_subset(expected_pipeline.get(field), live_pipeline.get(field)):
        raise SystemExit("ERROR: Live metrics pipeline does not contain the rendered ordered pipeline.")

expected_filelog = (((overlay.get("logsCollection") or {}).get("extraFileLogs") or {}).get("filelog/tetragon"))
if expected_filelog is not None:
    live_filelog = live_receivers.get("filelog/tetragon")
    if live_filelog is None or not mapping_subset(expected_filelog, live_filelog):
        raise SystemExit("ERROR: Live Tetragon filelog index/sourcetype/resource configuration drifted.")
PY

    selected_ready_pods() {
        local namespace="$1" selector="$2" payload
        payload="$("${KUBECTL[@]}" -n "${namespace}" get pods -l "${selector}" -o json 2>/dev/null)" || return 1
        python3 -c '
import json,sys
items = json.load(sys.stdin).get("items", [])
if not isinstance(items, list) or not items:
    raise SystemExit(1)
names = []
for pod in items:
    metadata = pod.get("metadata") or {}
    status = pod.get("status") or {}
    ready = any(item.get("type") == "Ready" and item.get("status") == "True" for item in status.get("conditions") or [])
    name = metadata.get("name")
    if not isinstance(name, str) or not name or status.get("phase") != "Running" or not ready or metadata.get("deletionTimestamp"):
        raise SystemExit(1)
    names.append(name)
print("\n".join(names))
' <<<"${payload}"
    }

    probe_pod_metrics() {
        local label="$1" namespace="$2" selector="$3" port="$4" pods pod path output count=0
        pods="$(selected_ready_pods "${namespace}" "${selector}")" || {
            log "ERROR: ${label} requires every selected pod to be Running and Ready."
            return 1
        }
        while IFS= read -r pod; do
            [[ -n "${pod}" ]] || continue
            count=$((count + 1))
            path="/api/v1/namespaces/${namespace}/pods/${pod}:${port}/proxy/metrics"
            output="$("${KUBECTL[@]}" get --raw "${path}" 2>/dev/null)" || {
                log "ERROR: ${label} has a selected pod with an unreachable metrics endpoint."
                return 1
            }
            if ! grep -Eq '^[A-Za-z_:][A-Za-z0-9_:]*(\{[^}]*\})?[[:space:]]+[-+0-9.N]' <<<"${output}"; then
                log "ERROR: ${label} has a selected pod without Prometheus samples."
                return 1
            fi
        done <<<"${pods}"
        if (( count == 0 )); then
            log "ERROR: ${label} selected no Ready pods."
            return 1
        fi
        log "    ${label}: ${count} selected pod endpoint(s) passed"
    }

    SCRAPE_JOBS=()
    while IFS= read -r job; do
        [[ -n "${job}" ]] && SCRAPE_JOBS+=("${job}")
    done < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1], encoding="utf-8"))["scrape_jobs"]))' "${OUTPUT_DIR}/metadata.json")
    for job in "${SCRAPE_JOBS[@]}"; do
        case "${job}" in
            prometheus/isovalent_cilium)
                probe_pod_metrics "cilium-agent:9962" "${CILIUM_NAMESPACE}" "k8s-app=cilium" 9962 ;;
            prometheus/isovalent_hubble)
                probe_pod_metrics "hubble-metrics:9965" "${CILIUM_NAMESPACE}" "k8s-app=cilium" 9965 ;;
            prometheus/isovalent_envoy)
                probe_pod_metrics "cilium-envoy:9964" "${CILIUM_NAMESPACE}" "k8s-app=cilium-envoy" 9964 ;;
            prometheus/isovalent_operator)
                probe_pod_metrics "cilium-operator:9963" "${CILIUM_NAMESPACE}" "io.cilium/app=operator" 9963 ;;
            prometheus/isovalent_tetragon)
                probe_pod_metrics "tetragon:2112" "${TETRAGON_NAMESPACE}" "app.kubernetes.io/name=tetragon" 2112 ;;
            prometheus/isovalent_tetragon_operator)
                probe_pod_metrics "tetragon-operator:2113" "${TETRAGON_NAMESPACE}" "app.kubernetes.io/name=tetragon-operator" 2113 ;;
            prometheus/isovalent_dnsproxy)
                probe_pod_metrics "cilium-dnsproxy:9967" "${CILIUM_NAMESPACE}" "k8s-app=cilium-dnsproxy" 9967 ;;
            *)
                log "ERROR: Unsupported rendered live probe receiver."
                exit 1
                ;;
        esac
    done
    log "  Live Kubernetes checks passed."
fi

if [[ "${SIGNALFLOW}" == "true" ]]; then
    log "  SignalFlow: requiring current Isovalent metric families..."
    python3 - "${OUTPUT_DIR}/metadata.json" "${O11Y_TOKEN_FILE}" "${API_LOOKBACK_SECONDS}" "${API_TIMEOUT_SECONDS}" "${ALLOW_LOOSE_TOKEN_PERMS}" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def token_from_file(path: str, allow_loose: bool) -> str:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RuntimeError("token file must be a regular file, not a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        raw = os.read(descriptor, 16 * 1024 + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino) or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("token file changed while it was read")
    if info.st_uid != os.geteuid() or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("token file ownership or link count is unsafe")
    if stat.S_IMODE(info.st_mode) != 0o600 and not allow_loose:
        raise RuntimeError("token file must be mode 600")
    if info.st_size <= 0 or info.st_size > 16 * 1024 or len(raw) != info.st_size:
        raise RuntimeError("token file has an invalid size")
    text = raw.decode("utf-8", "strict")
    if text.endswith("\r\n"):
        token = text[:-2]
    elif text.endswith("\n"):
        token = text[:-1]
    else:
        token = text
    if not token or "\x00" in token or any(character.isspace() for character in token):
        raise RuntimeError("token file must contain one token with at most one trailing newline")
    return token


def positive_count_point(value: object) -> bool:
    if isinstance(value, dict):
        direct = value.get("value")
        if isinstance(direct, (int, float)) and not isinstance(direct, bool):
            return direct > 0
        return any(positive_count_point(child) for child in value.values())
    if isinstance(value, list):
        # SignalFlow commonly encodes points as [timestamp, value].
        if len(value) >= 2 and isinstance(value[0], (int, float)):
            return positive_count_point(value[1])
        return any(positive_count_point(child) for child in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def positive_data(payload: object) -> bool:
    if isinstance(payload, dict):
        points = payload.get("data")
        if isinstance(points, list):
            return any(positive_count_point(point) for point in points)
        return any(positive_data(child) for child in payload.values())
    if isinstance(payload, list):
        return any(positive_data(child) for child in payload)
    return False


def require_metric(realm: str, token: str, cluster: str, metric: str, lookback: int, timeout: int) -> None:
    now_ms = int(time.time() * 1000)
    query = urllib.parse.urlencode({"start": now_ms - lookback * 1000, "stop": now_ms, "resolution": 10000})
    test_url = os.environ.get("ISOVALENT_SIGNALFLOW_TEST_URL", "")
    if test_url:
        parsed_test_url = urllib.parse.urlsplit(test_url)
        if (
            os.environ.get("ISOVALENT_VALIDATION_TEST_MODE") != "true"
            or parsed_test_url.scheme != "http"
            or parsed_test_url.hostname not in {"127.0.0.1", "::1"}
            or parsed_test_url.username is not None
            or parsed_test_url.password is not None
            or parsed_test_url.query
            or parsed_test_url.fragment
        ):
            raise RuntimeError("SignalFlow test endpoint is not an allowed loopback URL")
        url = test_url + "?" + query
    else:
        url = f"https://stream.{realm}.observability.splunkcloud.com/v2/signalflow/execute?{query}"
    program = f"data({json.dumps(metric)}, filter=filter(\"k8s.cluster.name\", {json.dumps(cluster)})).count().publish(label=\"isovalent_validation\")"
    request = urllib.request.Request(url, data=program.encode(), method="POST", headers={"Accept": "text/event-stream", "Content-Type": "text/plain", "X-SF-TOKEN": token})
    deadline = time.monotonic() + timeout
    event = ""
    data_lines: list[str] = []
    total = 0

    def finish_event() -> bool:
        nonlocal event, data_lines
        positive = False
        if event == "data" and data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                payload = None
            positive = positive_data(payload)
        event = ""
        data_lines = []
        return positive

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            while time.monotonic() < deadline:
                line = response.readline(64 * 1024)
                if not line:
                    break
                total += len(line)
                if total > 1024 * 1024:
                    raise RuntimeError("SignalFlow response exceeded the validation limit")
                decoded = line.decode("utf-8", "replace").rstrip("\r\n")
                if not decoded:
                    if finish_event():
                        return
                elif decoded.startswith("event:"):
                    event = decoded.partition(":")[2].strip()
                elif decoded.startswith("data:"):
                    data_lines.append(decoded.partition(":")[2].lstrip())
            if finish_event():
                return
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RuntimeError(f"SignalFlow returned HTTP {exc.code}; response body suppressed") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("SignalFlow request failed; details suppressed") from exc
    raise RuntimeError(f"SignalFlow returned no positive data for required metric {metric!r}")


try:
    metadata = json.load(open(sys.argv[1], encoding="utf-8"))
    token = token_from_file(sys.argv[2], sys.argv[5] == "true")
    jobs = set(metadata["scrape_jobs"])
    configured_metrics = metadata["signalflow_metrics"]
    metrics = []
    if "prometheus/isovalent_cilium" in jobs:
        metrics.append(configured_metrics["cilium"])
    if "prometheus/isovalent_hubble" in jobs:
        metrics.append(configured_metrics["hubble"])
    if "prometheus/isovalent_tetragon" in jobs:
        metrics.append(configured_metrics["tetragon"])
    if not metrics:
        raise RuntimeError("no core Cilium, Hubble, or Tetragon receiver is enabled for SignalFlow validation")
    for metric in metrics:
        require_metric(metadata["realm"], token, metadata["cluster_name"], metric, int(sys.argv[3]), int(sys.argv[4]))
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
    log "  SignalFlow checks passed."
fi

if [[ "${SPLUNK_SEARCH}" == "true" ]]; then
    log "  Splunk Platform: requiring current Isovalent events..."
    python3 - "${OUTPUT_DIR}/metadata.json" "${SPLUNK_MANAGEMENT_URL}" "${SPLUNK_SEARCH_TOKEN_FILE}" "${API_LOOKBACK_SECONDS}" "${API_TIMEOUT_SECONDS}" "${ALLOW_LOOSE_TOKEN_PERMS}" <<'PY'
from __future__ import annotations

import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request


def token_from_file(path: str, allow_loose: bool) -> str:
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise RuntimeError("token file must be a regular file, not a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        raw = os.read(descriptor, 16 * 1024 + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino) or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("token file changed while it was read")
    if info.st_uid != os.geteuid() or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("token file ownership or link count is unsafe")
    if stat.S_IMODE(info.st_mode) != 0o600 and not allow_loose:
        raise RuntimeError("token file must be mode 600")
    if info.st_size <= 0 or info.st_size > 16 * 1024 or len(raw) != info.st_size:
        raise RuntimeError("token file has an invalid size")
    text = raw.decode("utf-8", "strict")
    if text.endswith("\r\n"):
        token = text[:-2]
    elif text.endswith("\n"):
        token = text[:-1]
    else:
        token = text
    if not token or "\x00" in token or any(character.isspace() for character in token):
        raise RuntimeError("token file must contain one token with at most one trailing newline")
    return token


try:
    metadata = json.load(open(sys.argv[1], encoding="utf-8"))
    base_url = sys.argv[2].rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    test_loopback = (
        os.environ.get("ISOVALENT_VALIDATION_TEST_MODE") == "true"
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1"}
    )
    if (parsed.scheme != "https" and not test_loopback) or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise RuntimeError("Splunk management URL must be an absolute credential-free https:// URL")
    token = token_from_file(sys.argv[3], sys.argv[6] == "true")
    index = metadata["splunk_platform_index"]
    sourcetype = metadata["splunk_platform_sourcetype"]
    cluster = metadata["cluster_name"]
    search = f'search index={index} sourcetype="{sourcetype}" k8s.cluster.name="{cluster}" earliest=-{int(sys.argv[4])}s | head 1 | fields "k8s.cluster.name"'
    body = urllib.parse.urlencode({"search": search, "output_mode": "json"}).encode()
    request = urllib.request.Request(base_url + "/services/search/jobs/export", data=body, method="POST", headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(request, timeout=int(sys.argv[5])) as response:
            raw = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RuntimeError(f"Splunk search returned HTTP {exc.code}; response body suppressed") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Splunk search request failed; details suppressed") from exc
    if len(raw) > 1024 * 1024:
        raise RuntimeError("Splunk search response exceeded the validation limit")
    found = False
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(item, dict)
            and isinstance(item.get("result"), dict)
            and item["result"].get("k8s.cluster.name") == cluster
        ):
            found = True
            break
    if not found:
        raise RuntimeError("Splunk search returned no Isovalent events")
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
    log "  Splunk Platform search passed."
fi

log "Splunk Observability Isovalent Integration validation passed."
