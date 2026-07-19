#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/cisco-isovalent-platform-rendered"
LIVE=false
KUBE_CONTEXT=""
ALLOW_CURRENT_CONTEXT=false
CILIUM_NAMESPACE="kube-system"
TETRAGON_NAMESPACE="tetragon"
HUBBLE_ENTERPRISE_NAMESPACE="kube-system"
DNSPROXY_NAMESPACE="kube-system"
TIMESCAPE_NAMESPACE="hubble-timescape"
CILIUM_NS_SET=false
TETRAGON_NS_SET=false
AUDITED_OSS_CILIUM_CHART_VERSION="1.18.10"
AUDITED_ENTERPRISE_CILIUM_CHART_VERSION="1.18.8"
AUDITED_EKS_MIRROR_CILIUM_CHART_VERSION="1.18.8"
AUDITED_OSS_TETRAGON_CHART_VERSION="1.7.0"
AUDITED_ENTERPRISE_TETRAGON_CHART_VERSION="1.18.1"
AUDITED_DNSPROXY_CHART_VERSION="1.18.8"
AUDITED_HUBBLE_ENTERPRISE_CHART_VERSION="1.18.8"
AUDITED_TIMESCAPE_CHART_VERSION="1.18.8"

usage() {
    cat <<'EOF'
Cisco Isovalent Platform Setup validation

Usage:
  bash skills/cisco-isovalent-platform-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --kube-context CTX Kubernetes context for live checks
  --allow-current-context
                   Permit --live to use kubectl's active context
  --cilium-namespace NS
                     Namespace for Cilium services (default: from rendered
                     apply-plan.json, else kube-system)
  --tetragon-namespace NS
                     Namespace for Tetragon services (default: from rendered
                     apply-plan.json, else tetragon)
  --live             Run helm status / kubectl probes against the cluster
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
        --cilium-namespace) require_arg "$1" "$#" || exit 1; CILIUM_NAMESPACE="$2"; CILIUM_NS_SET=true; shift 2 ;;
        --tetragon-namespace) require_arg "$1" "$#" || exit 1; TETRAGON_NAMESPACE="$2"; TETRAGON_NS_SET=true; shift 2 ;;
        --live) LIVE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

# Adopt the namespaces recorded in the rendered apply-plan when the operator did
# not pass explicit flags. This lets setup.sh-driven validation (which only
# passes --output-dir) honor non-default namespaces from the spec; explicit
# --cilium-namespace/--tetragon-namespace still win, and the kube-system/tetragon
# defaults remain when the plan is absent or omits them.
if [[ -f "${OUTPUT_DIR}/apply-plan.json" ]]; then
    if ! rendered_namespaces="$(python3 - "${OUTPUT_DIR}/apply-plan.json" <<'PY'
import json
import re
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
namespaces = (data.get("live_action_state_contract") or {}).get("namespaces")
if not isinstance(namespaces, dict):
    raise SystemExit("apply-plan namespace contract is missing")
keys = ("cilium", "tetragon", "hubble_enterprise", "cilium_dnsproxy", "hubble_timescape")
pattern = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
values = []
for key in keys:
    value = namespaces.get(key)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise SystemExit(f"invalid rendered namespace for {key}")
    values.append(value)
print("\t".join(values))
PY
)"; then
        log "ERROR: Invalid namespace contract in apply-plan.json."
        exit 1
    fi
    IFS=$'\t' read -r rendered_cilium_ns rendered_tetragon_ns rendered_hubble_ns rendered_dnsproxy_ns rendered_timescape_ns <<< "${rendered_namespaces}"
    if [[ "${CILIUM_NS_SET}" == "false" && -n "${rendered_cilium_ns}" ]]; then
        CILIUM_NAMESPACE="${rendered_cilium_ns}"
    fi
    if [[ "${TETRAGON_NS_SET}" == "false" && -n "${rendered_tetragon_ns}" ]]; then
        TETRAGON_NAMESPACE="${rendered_tetragon_ns}"
    fi
    HUBBLE_ENTERPRISE_NAMESPACE="${rendered_hubble_ns}"
    DNSPROXY_NAMESPACE="${rendered_dnsproxy_ns}"
    TIMESCAPE_NAMESPACE="${rendered_timescape_ns}"
fi

python3 - "${CILIUM_NAMESPACE}" "${TETRAGON_NAMESPACE}" <<'PY'
import re
import sys

pattern = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
for value in sys.argv[1:]:
    if not pattern.fullmatch(value):
        raise SystemExit("ERROR: explicit namespace flags must be Kubernetes DNS-1123 labels")
PY

check_file() {
    local path="$1"
    [[ -f "${path}" ]] || { log "ERROR: Missing ${path}"; exit 1; }
}

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/helm/cilium-values.yaml"
check_file "${OUTPUT_DIR}/helm/tetragon-values.yaml"
check_file "${OUTPUT_DIR}/scripts/install-cilium.sh"
check_file "${OUTPUT_DIR}/scripts/install-tetragon.sh"
check_file "${OUTPUT_DIR}/scripts/preflight.sh"
check_file "${OUTPUT_DIR}/feature-catalog.json"
check_file "${OUTPUT_DIR}/feature-matrix.md"
check_file "${OUTPUT_DIR}/coverage-report.json"
check_file "${OUTPUT_DIR}/environment-profiles.json"
check_file "${OUTPUT_DIR}/environment-profiles.md"
check_file "${OUTPUT_DIR}/apply-plan.json"
check_file "${OUTPUT_DIR}/doctor-report.md"

python3 - \
    "${OUTPUT_DIR}/metadata.json" \
    "${AUDITED_OSS_CILIUM_CHART_VERSION}" \
    "${AUDITED_ENTERPRISE_CILIUM_CHART_VERSION}" \
    "${AUDITED_EKS_MIRROR_CILIUM_CHART_VERSION}" \
    "${AUDITED_OSS_TETRAGON_CHART_VERSION}" \
    "${AUDITED_ENTERPRISE_TETRAGON_CHART_VERSION}" \
    "${AUDITED_DNSPROXY_CHART_VERSION}" \
    "${AUDITED_HUBBLE_ENTERPRISE_CHART_VERSION}" \
    "${AUDITED_TIMESCAPE_CHART_VERSION}" <<'PY'
import json
import re
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
edition = metadata.get("edition")
if edition not in {"oss", "enterprise"}:
    raise SystemExit("ERROR: metadata.json has an invalid edition")
eks_mirror = metadata.get("eks_mirror") is True
cilium_version = sys.argv[4] if eks_mirror else sys.argv[3] if edition == "enterprise" else sys.argv[2]
tetragon_version = sys.argv[5] if edition == "oss" else sys.argv[6]
versions = dict(
    zip(
        ("cilium", "tetragon", "cilium-dnsproxy", "hubble-enterprise", "hubble-timescape"),
        (cilium_version, tetragon_version, *sys.argv[7:]),
    )
)
charts = metadata.get("helm_charts")
if not isinstance(charts, dict) or set(charts) != set(versions):
    raise SystemExit("ERROR: metadata.json has an incomplete Helm chart contract")
for release, expected_version in versions.items():
    item = charts.get(release)
    if not isinstance(item, dict):
        raise SystemExit(f"ERROR: Helm chart contract for {release} must be a mapping")
    if item.get("version") != expected_version:
        raise SystemExit(
            f"ERROR: Helm chart contract for {release} must pin audited version {expected_version}"
        )
    names = item.get("helm_list_chart_names")
    if not isinstance(names, list) or not names or any(
        not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name)
        for name in names
    ):
        raise SystemExit(f"ERROR: Helm chart identities for {release} are invalid")
    if not isinstance(item.get("chart"), str) or not item["chart"]:
        raise SystemExit(f"ERROR: Helm chart source for {release} is missing")
    if item.get("archive_sha256") is not None:
        raise SystemExit(
            f"ERROR: unverified chart checksum recorded for {release}; this repo has no audited archive digest"
        )
if not isinstance(metadata.get("chart_provenance_gap"), str) or not metadata["chart_provenance_gap"].strip():
    raise SystemExit("ERROR: metadata.json must record the upstream chart provenance gap")
PY

# Parse every rendered YAML/JSON document and reject inline credential values by
# key.  Diagnostics report only the file and structured key path, never the
# value.  Placeholder/file-indirection markers remain allowed.
PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" python3 - "${OUTPUT_DIR}" <<'PY'
import json
import re
import sys
from pathlib import Path

from yaml_compat import YamlCompatError, load_yaml_or_json

root = Path(sys.argv[1])
secret_keys = {
    "license",
    "licensekey",
    "licensevalue",
    "token",
    "accesstoken",
    "apitoken",
    "hectoken",
    "password",
    "apikey",
    "clientsecret",
    "privatekey",
    "authorization",
}
allowed_markers = {
    "__FILE_BACKED__",
    "__REDACTED__",
    "PLACEHOLDER_HEC_TOKEN",
}


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def contains_material(value):
    if value is None or value is False or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        if stripped in allowed_markers or stripped.startswith("PLACEHOLDER_"):
            return False
        if stripped.startswith("${") and stripped.endswith("}"):
            return False
    return True


findings = []


def walk(value, path, source):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + [str(key)]
            if normalized(key) in secret_keys and contains_material(child):
                findings.append((source, ".".join(child_path)))
            walk(child, child_path, source)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, path + [str(index)], source)


for path in sorted(root.rglob("*")):
    if path.suffix.lower() not in {".json", ".yaml", ".yml"}:
        continue
    relative = str(path.relative_to(root))
    if path.is_symlink() or not path.is_file():
        findings.append((relative, "<unsafe-file>"))
        continue
    try:
        text = path.read_text(encoding="utf-8")
        payload = load_yaml_or_json(text, source=relative)
    except (OSError, UnicodeError, YamlCompatError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: unable to parse rendered structured file {relative}: {type(exc).__name__}")
    walk(payload, [], relative)

if findings:
    for source, key_path in findings:
        print(f"ERROR: inline credential material found in {source} at {key_path}", file=sys.stderr)
    raise SystemExit(1)
PY

python3 - "${OUTPUT_DIR}/coverage-report.json" "${OUTPUT_DIR}/feature-catalog.json" <<'PY'
import json
import sys
from pathlib import Path

coverage = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
catalog = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
allowed = set(catalog["allowed_statuses"])
if coverage.get("missing_features"):
    raise SystemExit("ERROR: coverage-report.json has missing_features: " + ", ".join(coverage["missing_features"]))
for feature in coverage.get("features", []):
    status = feature.get("status")
    if status not in allowed:
        raise SystemExit(f"ERROR: invalid feature status {status!r} for {feature.get('id')}")
    if status in {"unsupported_with_reason", "not_applicable", "gated_private"} and not feature.get("reason"):
        raise SystemExit(f"ERROR: {feature.get('id')} has status {status} without reason")
PY

# Tetragon export configuration is part of the required logging contract. Do
# not silently fall back to file mode when the values file is malformed.
if ! EXPORT_MODE="$(PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" python3 - "${OUTPUT_DIR}/helm/tetragon-values.yaml" <<'PY'
import sys
from pathlib import Path

from yaml_compat import load_yaml_or_json

path = Path(sys.argv[1])
data = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
if not isinstance(data, dict) or not isinstance(data.get("tetragon"), dict):
    raise SystemExit("ERROR: tetragon-values.yaml must contain a tetragon mapping")

tetragon = data["tetragon"]
if not str(tetragon.get("clusterName", "")).strip():
    raise SystemExit("ERROR: tetragon.clusterName must be non-empty")

export = tetragon.get("export") or {}
if not isinstance(export, dict):
    raise SystemExit("ERROR: tetragon.export must be a mapping when present")
mode = str(export.get("mode") or "file")
if mode not in {"file", "stdout", "fluentd"}:
    raise SystemExit(f"ERROR: unsupported Tetragon export mode: {mode}")
if mode == "file":
    if not str(tetragon.get("exportDirectory", "")).strip():
        raise SystemExit("ERROR: file export requires tetragon.exportDirectory")
    if not str(tetragon.get("exportFilename", "")).strip():
        raise SystemExit("ERROR: file export requires tetragon.exportFilename")
elif mode == "stdout":
    if str(export.get("mode", "")) != "stdout":
        raise SystemExit("ERROR: stdout export requires tetragon.export.mode=stdout")
elif mode == "fluentd":
    if str(export.get("mode", "")) != "fluentd":
        raise SystemExit("ERROR: fluentd export requires tetragon.export.mode=fluentd")
    fluentd = export.get("fluentd")
    if not isinstance(fluentd, dict):
        raise SystemExit("ERROR: fluentd export requires tetragon.export.fluentd mapping")
    output = fluentd.get("output")
    if not isinstance(output, str) or not output.strip():
        raise SystemExit("ERROR: fluentd export requires non-empty tetragon.export.fluentd.output")
    directives = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            raise SystemExit("ERROR: fluentd output contains a malformed directive")
        key, value = parts
        if key in directives:
            raise SystemExit(f"ERROR: fluentd output contains duplicate {key} directive")
        directives[key] = value.strip()
    required = {"@type", "host", "port", "token", "default_index", "use_ssl"}
    missing = sorted(required - set(directives))
    if missing:
        raise SystemExit("ERROR: fluentd output is missing required directives: " + ", ".join(missing))
    if directives["@type"] != "splunk_hec":
        raise SystemExit("ERROR: fluentd output @type must be splunk_hec")
    if not directives["port"].isdigit() or not (1 <= int(directives["port"]) <= 65535):
        raise SystemExit("ERROR: fluentd output port must be an integer from 1 to 65535")
    if directives["token"] != "PLACEHOLDER_HEC_TOKEN":
        raise SystemExit("ERROR: fluentd output token must remain PLACEHOLDER_HEC_TOKEN for file-backed handoff")
    if directives["use_ssl"].lower() not in {"true", "false"}:
        raise SystemExit("ERROR: fluentd output use_ssl must be true or false")

print(mode)
PY
)"; then
    log "ERROR: Invalid Tetragon export configuration."
    exit 1
fi

if [[ "${EXPORT_MODE}" == "fluentd" ]]; then
    log "  WARN: Tetragon export mode is 'fluentd' (DEPRECATED, fluent-plugin-splunk-hec archived 2025-06-24)."
fi

log "Cisco Isovalent Platform Setup rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    if [[ -z "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" != "true" ]]; then
        log "  ERROR: --live requires --kube-context CTX, or --allow-current-context to use kubectl's active context."
        exit 1
    fi
    log "  --live: probing cluster..."
    if ! command -v helm >/dev/null 2>&1; then
        log "  ERROR: helm not on PATH."
        exit 1
    fi
    if ! command -v kubectl >/dev/null 2>&1; then
        log "  ERROR: kubectl not on PATH."
        exit 1
    fi
    KUBECTL=(kubectl)
    HELM=(helm)
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        KUBECTL=(kubectl --context "${KUBE_CONTEXT}")
        HELM=(helm --kube-context "${KUBE_CONTEXT}")
    fi
    LIVE_FAILURES=0
    record_failure() {
        log "    ERROR: $*"
        LIVE_FAILURES=$((LIVE_FAILURES + 1))
    }

    check_kubectl_skew() {
        local output summary
        if ! output="$("${KUBECTL[@]}" version -o json 2>&1)"; then
            record_failure "unable to query kubectl/API-server versions: $(printf '%s\n' "${output}" | head -1)"
            return 0
        fi
        if ! summary="$(printf '%s' "${output}" | python3 -c '
import json
import re
import sys

payload = json.load(sys.stdin)


def component(value, label):
    if not isinstance(value, dict) or str(value.get("major")) != "1":
        raise SystemExit(f"{label} major version is not Kubernetes 1.x")
    match = re.match(r"^[0-9]+", str(value.get("minor") or ""))
    if not match:
        raise SystemExit(f"{label} minor version is invalid")
    return int(match.group())


client = component(payload.get("clientVersion"), "kubectl")
server = component(payload.get("serverVersion"), "kube-apiserver")
if abs(client - server) > 1:
    raise SystemExit(
        f"kubectl 1.{client} is outside the supported +/-1 minor skew for kube-apiserver 1.{server}"
    )
print(f"kubectl 1.{client}; kube-apiserver 1.{server}; skew supported")
' 2>&1)"; then
            record_failure "${summary}"
            return 0
        fi
        log "    ${summary}"
    }

    log "  Kubernetes client compatibility:"
    check_kubectl_skew

    if ! LIVE_PROFILE="$(python3 - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
fields = (
    str(metadata.get("edition") or "oss"),
    str(metadata.get("distribution") or "generic"),
    "true" if metadata.get("enable_dnsproxy") is True else "false",
    "true" if metadata.get("enable_hubble_enterprise") is True else "false",
    "true" if metadata.get("enable_timescape") is True else "false",
    "true" if metadata.get("eks_mirror") is True else "false",
)
print("\t".join(fields))
PY
)"; then
        log "  ERROR: unable to read live validation expectations from metadata.json."
        exit 1
    fi
    IFS=$'\t' read -r EDITION DISTRIBUTION ENABLE_DNSPROXY ENABLE_HUBBLE_ENTERPRISE ENABLE_TIMESCAPE EKS_MIRROR <<< "${LIVE_PROFILE}"

    PROVIDER_MANAGED_CILIUM=false
    case "${DISTRIBUTION}" in
        aks-managed-cilium|gke-dataplane-v2) PROVIDER_MANAGED_CILIUM=true ;;
    esac

    # Helm list exposes Chart.yaml identity/version but not repository origin.
    # Exact version pins are therefore enforced here while the remaining
    # provenance gap stays explicit in metadata.json.
    if [[ "${EDITION}" == "enterprise" ]]; then
        CILIUM_CHART_NAMES='cilium-enterprise,cilium'
        CILIUM_CHART_LABEL='Enterprise Cilium (cilium-enterprise or cilium Chart.yaml name)'
        EXPECTED_TETRAGON_CHART_VERSION="${AUDITED_ENTERPRISE_TETRAGON_CHART_VERSION}"
    else
        CILIUM_CHART_NAMES='cilium'
        CILIUM_CHART_LABEL='OSS Cilium (cilium)'
        EXPECTED_TETRAGON_CHART_VERSION="${AUDITED_OSS_TETRAGON_CHART_VERSION}"
    fi
    if [[ "${EKS_MIRROR}" == "true" ]]; then
        EXPECTED_CILIUM_CHART_VERSION="${AUDITED_EKS_MIRROR_CILIUM_CHART_VERSION}"
    elif [[ "${EDITION}" == "enterprise" ]]; then
        EXPECTED_CILIUM_CHART_VERSION="${AUDITED_ENTERPRISE_CILIUM_CHART_VERSION}"
    else
        EXPECTED_CILIUM_CHART_VERSION="${AUDITED_OSS_CILIUM_CHART_VERSION}"
    fi

    if ! HELM_RELEASES_JSON="$("${HELM[@]}" list --all-namespaces \
        --deployed --failed --pending --uninstalling --superseded --uninstalled \
        --output json 2>&1)"; then
        record_failure "unable to inventory Helm releases: $(printf '%s\n' "${HELM_RELEASES_JSON}" | head -1)"
        HELM_RELEASES_JSON='[]'
    fi

    release_record() {
        local release="$1"
        printf '%s' "${HELM_RELEASES_JSON}" | python3 -c '
import json
import sys

release = sys.argv[1]
items = json.load(sys.stdin)
if not isinstance(items, list):
    raise SystemExit("Helm list output was not a JSON array")
matches = [item for item in items if item.get("name") == release]
if len(matches) > 1:
    locations = ", ".join(
        "{}/{}".format(item.get("namespace") or "<unknown>", item.get("chart") or "<unknown-chart>")
        for item in matches
    )
    raise SystemExit(f"duplicate Helm releases named {release} found across namespaces: {locations}")
if matches:
    item = matches[0]
    print(item.get("namespace", ""))
' "${release}"
    }

    check_helm_release() {
        local release="$1" required="$2" expected_chart_names="$3" expected_version="$4" expected_chart_label="$5"
        local expected_namespace="${6:-}" record namespace current_namespace current_chart
        if ! record="$(release_record "${release}" 2>&1)"; then
            record_failure "unable to parse Helm inventory while checking ${release}: ${record}"
            return 0
        fi
        if [[ -z "${record}" ]]; then
            if [[ "${required}" == "true" ]]; then
                record_failure "required Helm release ${release} is not installed"
            else
                log "    ${release}: optional release not installed"
            fi
            return 0
        fi
        namespace="${record}"
        if [[ -z "${namespace}" ]]; then
            record_failure "Helm release ${release} has no namespace in inventory"
            return 0
        fi
        current_namespace="${expected_namespace:-${namespace}}"
        # `helm list` is used only to locate the unique release. Its status,
        # namespace, and chart fields are a snapshot and are not authoritative.
        # Stream the current, notes-free metadata document into one strict
        # parser so identity, exact chart version, and deployed state all come
        # from the same read without retaining customer-controlled content.
        if ! current_chart="$("${HELM[@]}" get metadata "${release}" -n "${current_namespace}" --output json 2>/dev/null \
            | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if not isinstance(payload, dict):
    raise SystemExit(1)
release, namespace, chart_names, version = sys.argv[1:]
allowed_charts = set(chart_names.split(","))
actual_version = str(payload.get("version") or "")
if not (
    payload.get("name") == release
    and payload.get("namespace") == namespace
    and payload.get("chart") in allowed_charts
    and actual_version in {version, "v" + version}
    and str(payload.get("status") or "").lower() == "deployed"
):
    raise SystemExit(1)
print("{}-{}".format(payload.get("chart"), actual_version))
' "${release}" "${current_namespace}" "${expected_chart_names}" "${expected_version}" 2>/dev/null)"; then
            record_failure "helm status did not confirm a current deployed release for ${release} in ${current_namespace}, expected ${expected_chart_label} at exact version ${expected_version}; command output suppressed"
            return 0
        fi
        log "    ${release} (${current_namespace}): chart ${current_chart}; current Helm status deployed"
    }

    fetch_and_check_pods() {
        local label="$1" namespace="$2" selector="$3" result_var="$4" output summary
        if ! output="$("${KUBECTL[@]}" -n "${namespace}" get pods -l "${selector}" -o json 2>&1)"; then
            if [[ -n "${result_var}" ]]; then
                printf -v "${result_var}" '%s' ''
            fi
            record_failure "unable to list ${label} pods in ${namespace}: $(printf '%s\n' "${output}" | head -1)"
            return 0
        fi
        if [[ -n "${result_var}" ]]; then
            printf -v "${result_var}" '%s' "${output}"
        fi
        if ! summary="$(printf '%s' "${output}" | python3 -c '
import json
import sys

label = sys.argv[1]
payload = json.load(sys.stdin)
items = payload.get("items") if isinstance(payload, dict) else None
if not isinstance(items, list) or not items:
    raise SystemExit(f"no {label} pods matched the required selector")
bad = []
for pod in items:
    metadata = pod.get("metadata") or {}
    spec = pod.get("spec") or {}
    status = pod.get("status") or {}
    name = metadata.get("name") or "<unnamed>"
    expected = {container.get("name") for container in spec.get("containers") or [] if container.get("name")}
    ready = {
        item.get("name")
        for item in status.get("containerStatuses") or []
        if item.get("ready") is True
    }
    if metadata.get("deletionTimestamp") or status.get("phase") != "Running" or not expected or not expected.issubset(ready):
        bad.append(name)
if bad:
    raise SystemExit(f"unready {label} pods: {chr(44).join(bad)}")
print(f"{len(items)}/{len(items)} ready")
' "${label}" 2>&1)"; then
            record_failure "${summary}"
            return 0
        fi
        log "    ${label}: ${summary}"
    }

    probe_metrics() {
        local label="$1" path="$2" required="${3:-true}" check_cilium_hive="${4:-false}" output status summary
        output="$("${KUBECTL[@]}" get --raw "${path}" 2>&1)" && status=0 || status=$?
        if [[ "${status}" -ne 0 ]]; then
            if [[ "${required}" == "false" && "${output}" =~ (NotFound|not[[:space:]]found|404) ]]; then
                log "    ${label}: optional service not installed"
                return 0
            fi
            record_failure "${label} metrics not reachable: $(printf '%s\n' "${output}" | head -1)"
            return 0
        fi
        if ! summary="$(python3 -c '
import math
import re
import sys

check_hive = sys.argv[1] == "true"
number = r"(?:NaN|[+-]?Inf|[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?)"
label_body = r"(?:\"(?:\\.|[^\"\\])*\"|\\.|[^{}\"])*"
sample = re.compile(
    rf"^[ \t]*(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)"
    rf"(?:\{{(?P<labels>{label_body})\}})?[ \t]+"
    rf"(?P<value>{number})"
    rf"(?:[ \t]+[+-]?[0-9]+(?:\.[0-9]+)?)?"
    rf"(?:[ \t]+\#.*)?[ \t]*$"
)
status_label = re.compile(r"(?:^|,)\s*status\s*=\s*\"(?P<status>(?:\\.|[^\"\\])*)\"")
sample_count = 0
unhealthy_total = 0.0
invalid_health_value = False
for line in sys.stdin:
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    match = sample.fullmatch(line.rstrip("\r\n"))
    if not match:
        continue
    sample_count += 1
    if not check_hive or match.group("name") != "cilium_hive_status":
        continue
    labels = match.group("labels") or ""
    label_match = status_label.search(labels)
    if not label_match or label_match.group("status") not in {"degraded", "failed"}:
        continue
    value_text = match.group("value")
    try:
        value = float(value_text)
    except ValueError:
        invalid_health_value = True
        continue
    if not math.isfinite(value):
        invalid_health_value = True
    elif value > 0:
        unhealthy_total += value
if sample_count == 0:
    raise SystemExit("returned no Prometheus/OpenMetrics samples")
if invalid_health_value:
    raise SystemExit("cilium_hive_status rule=degraded-or-failed-positive count=invalid")
if unhealthy_total > 0:
    count = format(unhealthy_total, ".15g")
    raise SystemExit(f"cilium_hive_status rule=degraded-or-failed-positive count={count}")
print(f"samples={sample_count}")
' "${check_cilium_hive}" <<< "${output}" 2>&1)"; then
            record_failure "${label}: ${summary}"
            return 0
        fi
        log "    ${label}: reachable (${summary})"
    }

    check_tetragon_pod_logs() {
        local pod_targets pod container output path log_scan
        if [[ -z "${TETRAGON_PODS_JSON}" ]]; then
            record_failure "Tetragon pod log validation could not run without a valid pod inventory"
            return 0
        fi
        if ! pod_targets="$(printf '%s' "${TETRAGON_PODS_JSON}" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
for pod in payload.get("items") or []:
    metadata = pod.get("metadata") or {}
    spec = pod.get("spec") or {}
    status = pod.get("status") or {}
    if status.get("phase") != "Running":
        continue
    names = [item.get("name") for item in spec.get("containers") or [] if item.get("name")]
    if not names:
        continue
    container = "tetragon" if "tetragon" in names else names[0]
    print("{}\t{}".format(metadata.get("name", ""), container))
' 2>&1)"; then
            record_failure "unable to select Tetragon pod log targets: ${pod_targets}"
            return 0
        fi
        if [[ -z "${pod_targets}" ]]; then
            record_failure "no running Tetragon pod was available for log validation"
            return 0
        fi
        while IFS=$'\t' read -r pod container; do
            [[ -n "${pod}" && -n "${container}" ]] || continue
            path="/api/v1/namespaces/${TETRAGON_NAMESPACE}/pods/${pod}/log?container=${container}&tailLines=20"
            if ! output="$("${KUBECTL[@]}" get --raw "${path}" 2>&1)"; then
                record_failure "Tetragon pod log API failed for ${pod}/${container}: $(printf '%s\n' "${output}" | head -1)"
                continue
            fi
            if [[ -z "${output//[[:space:]]/}" ]]; then
                record_failure "Tetragon pod log API returned an empty response for ${pod}/${container}"
                continue
            fi
            if ! log_scan="$(printf '%s\n' "${output}" | python3 -c '
import re
import sys

text = sys.stdin.read()
rules = (
    ("panic", re.compile(r"\bpanic(?:ked)?\b", re.IGNORECASE)),
    (
        "fatal",
        re.compile(
            r"(?:[\"\x27]?level[\"\x27]?\s*[:=]\s*[\"\x27]?fatal\b|\bfatal(?:\s+error)?\b)",
            re.IGNORECASE,
        ),
    ),
    ("runtime-error", re.compile(r"\bruntime(?:\s+|_)?error\b", re.IGNORECASE)),
    (
        "export-error",
        re.compile(
            r"(?:\b(?:export|exporter|exporting)\b[^\n]{0,120}\b(?:error|failed|failure|denied|unable)\b|"
            r"\b(?:error|failed|failure|denied|unable)\b[^\n]{0,120}\b(?:export|exporter|exporting)\b)",
            re.IGNORECASE,
        ),
    ),
)
matched = [name for name, pattern in rules if pattern.search(text)]
if matched:
    print(",".join(matched))
    raise SystemExit(1)
print("clean")
' 2>&1)"; then
                # log_scan contains rule identifiers only. Never echo the
                # matched log line because it may contain workload data.
                record_failure "Tetragon pod ${pod}/${container} matched recent fatal log rule(s): ${log_scan}"
                continue
            fi
            log "    ${pod}/${container}: pod logs reachable"
        done <<< "${pod_targets}"
    }

    check_timescape_workloads() {
        local output records namespace name owner desired current updated ready generation observed revision_state rollout_state reasons found=false
        local expected_owner="cilium" expected_namespace="${CILIUM_NAMESPACE}"
        if [[ -n "${TIMESCAPE_STANDALONE_RECORD}" ]]; then
            expected_owner="hubble-timescape"
            IFS=$'\t' read -r expected_namespace _ _ <<< "${TIMESCAPE_STANDALONE_RECORD}"
            if [[ -z "${expected_namespace}" ]]; then
                record_failure "standalone Hubble Timescape release has no namespace in Helm inventory"
                return 0
            fi
        fi
        if ! output="$("${KUBECTL[@]}" get statefulsets.apps --all-namespaces -o json 2>&1)"; then
            if [[ "${ENABLE_TIMESCAPE}" == "true" ]]; then
                record_failure "unable to discover required Hubble Timescape workloads: $(printf '%s\n' "${output}" | head -1)"
            else
                log "    WARN: optional Hubble Timescape workload discovery unavailable: $(printf '%s\n' "${output}" | head -1)"
            fi
            return 0
        fi
        if ! records="$(printf '%s' "${output}" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
for item in payload.get("items") or []:
    metadata = item.get("metadata") or {}
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    labels = metadata.get("labels") or {}
    annotations = metadata.get("annotations") or {}
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
    evidence = [metadata.get("name", ""), *labels.keys(), *labels.values()]
    for container in containers:
        evidence.extend((container.get("name", ""), container.get("image", "")))
    if "timescape" not in " ".join(str(value) for value in evidence).lower():
        continue
    owner = annotations.get("meta.helm.sh/release-name") or labels.get("app.kubernetes.io/instance") or "-"
    desired = int(spec.get("replicas") or 0)
    current = int(status.get("currentReplicas") if status.get("currentReplicas") is not None else -1)
    updated = int(status.get("updatedReplicas") if status.get("updatedReplicas") is not None else -1)
    ready = int(status.get("readyReplicas") if status.get("readyReplicas") is not None else -1)
    generation = int(metadata.get("generation") if metadata.get("generation") is not None else -1)
    observed = int(status.get("observedGeneration") if status.get("observedGeneration") is not None else -1)
    current_revision = str(status.get("currentRevision") or "")
    update_revision = str(status.get("updateRevision") or "")
    revision_state = "match" if current_revision and current_revision == update_revision else "mismatch"
    reasons = []
    if desired < 1:
        reasons.append("desired-zero")
    if generation < 0 or observed < generation:
        reasons.append("observed-generation-stale")
    if current != desired:
        reasons.append("current-replicas-mismatch")
    if updated != desired:
        reasons.append("updated-replicas-mismatch")
    if ready != desired:
        reasons.append("ready-replicas-mismatch")
    if revision_state != "match":
        reasons.append("revision-mismatch")
    rollout_state = "complete" if not reasons else "incomplete"
    print("{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(
        metadata.get("namespace", "default"),
        metadata.get("name", ""),
        owner,
        desired,
        current,
        updated,
        ready,
        generation,
        observed,
        revision_state,
        rollout_state,
        ",".join(reasons) or "none",
    ))
' 2>&1)"; then
            record_failure "unable to parse Hubble Timescape workload inventory: ${records}"
            return 0
        fi
        while IFS=$'\t' read -r namespace name owner desired current updated ready generation observed revision_state rollout_state reasons; do
            [[ -n "${name}" ]] || continue
            found=true
            if [[ "${namespace}" != "${expected_namespace}" ]]; then
                record_failure "Hubble Timescape StatefulSet ${namespace}/${name} is outside expected namespace ${expected_namespace}"
                continue
            fi
            if [[ "${owner}" != "${expected_owner}" ]]; then
                record_failure "Hubble Timescape StatefulSet ${namespace}/${name} has Helm owner ${owner}, expected ${expected_owner}"
                continue
            fi
            if [[ "${rollout_state}" != "complete" ]]; then
                record_failure "Hubble Timescape StatefulSet ${namespace}/${name} rollout is incomplete (${reasons}); desired=${desired} current=${current} updated=${updated} ready=${ready} generation=${generation} observed=${observed} revision=${revision_state}"
                continue
            fi
            if [[ "${owner}" == "cilium" && -z "${TIMESCAPE_STANDALONE_RECORD}" ]]; then
                log "    hubble-timescape: bundled with cilium release as StatefulSet ${namespace}/${name} (rollout complete, ${ready}/${desired} ready)"
            else
                log "    hubble-timescape: StatefulSet ${namespace}/${name}, Helm owner ${owner} (rollout complete, ${ready}/${desired} ready)"
            fi
        done <<< "${records}"
        if [[ "${found}" != "true" && ( "${ENABLE_TIMESCAPE}" == "true" || -n "${TIMESCAPE_STANDALONE_RECORD}" ) ]]; then
            record_failure "Hubble Timescape was expected but no Timescape StatefulSet was found"
        elif [[ "${found}" != "true" ]]; then
            log "    hubble-timescape: optional add-on not installed (standalone or cilium-bundled)"
        fi
    }

    log "  Helm release health:"
    if [[ "${PROVIDER_MANAGED_CILIUM}" == "true" ]]; then
        record_failure "provider-managed Cilium live evidence is unsupported for ${DISTRIBUTION}; skipped Helm-owned Cilium pod and service probes, so this run cannot be production acceptance evidence"
        if ! MANAGED_CILIUM_RECORD="$(release_record cilium 2>&1)"; then
            record_failure "unable to parse Helm inventory while checking provider-managed Cilium: ${MANAGED_CILIUM_RECORD}"
        elif [[ -n "${MANAGED_CILIUM_RECORD}" ]]; then
            record_failure "provider-managed ${DISTRIBUTION} unexpectedly has a user-visible Helm release named cilium: ${MANAGED_CILIUM_RECORD}"
        else
            log "    cilium: provider-managed ${DISTRIBUTION} profile; no Helm release expected"
        fi
    else
        check_helm_release cilium true "${CILIUM_CHART_NAMES}" "${EXPECTED_CILIUM_CHART_VERSION}" "${CILIUM_CHART_LABEL}" "${CILIUM_NAMESPACE}"
    fi
    check_helm_release tetragon true "tetragon" "${EXPECTED_TETRAGON_CHART_VERSION}" "Tetragon (tetragon)" "${TETRAGON_NAMESPACE}"
    check_helm_release hubble-enterprise "${ENABLE_HUBBLE_ENTERPRISE}" "hubble-enterprise" "${AUDITED_HUBBLE_ENTERPRISE_CHART_VERSION}" "Hubble Enterprise (hubble-enterprise)" "${HUBBLE_ENTERPRISE_NAMESPACE}"
    check_helm_release cilium-dnsproxy "${ENABLE_DNSPROXY}" "cilium-dnsproxy" "${AUDITED_DNSPROXY_CHART_VERSION}" "Cilium DNSProxy (cilium-dnsproxy)" "${DNSPROXY_NAMESPACE}"
    if ! TIMESCAPE_STANDALONE_RECORD="$(release_record hubble-timescape 2>&1)"; then
        record_failure "unable to parse Helm inventory while checking hubble-timescape: ${TIMESCAPE_STANDALONE_RECORD}"
        TIMESCAPE_STANDALONE_RECORD=""
    elif [[ -n "${TIMESCAPE_STANDALONE_RECORD}" ]]; then
        check_helm_release hubble-timescape true "hubble-timescape" "${AUDITED_TIMESCAPE_CHART_VERSION}" "Hubble Timescape (hubble-timescape)" "${TIMESCAPE_NAMESPACE}"
    else
        log "    hubble-timescape: no standalone release; checking for a cilium-bundled StatefulSet"
    fi

    log "  Required platform pod readiness:"
    TETRAGON_PODS_JSON=""
    if [[ "${PROVIDER_MANAGED_CILIUM}" == "true" ]]; then
        log "    cilium: skipped Helm-owned pod selector for provider-managed ${DISTRIBUTION}"
    else
        fetch_and_check_pods "Cilium agent" "${CILIUM_NAMESPACE}" "k8s-app=cilium" ""
    fi
    fetch_and_check_pods "Tetragon agent" "${TETRAGON_NAMESPACE}" "app.kubernetes.io/name=tetragon" TETRAGON_PODS_JSON
    if [[ "${ENABLE_HUBBLE_ENTERPRISE}" == "true" ]]; then
        fetch_and_check_pods "Hubble Enterprise" "${HUBBLE_ENTERPRISE_NAMESPACE}" "app.kubernetes.io/instance=hubble-enterprise" ""
    fi
    if [[ "${ENABLE_DNSPROXY}" == "true" ]]; then
        fetch_and_check_pods "Cilium DNSProxy" "${DNSPROXY_NAMESPACE}" "k8s-app=cilium-dnsproxy" ""
    fi

    log "  Metrics endpoints via the Kubernetes service API proxy:"
    if [[ "${PROVIDER_MANAGED_CILIUM}" == "true" ]]; then
        log "    cilium metrics: skipped Helm-owned service names for provider-managed ${DISTRIBUTION}"
    else
        probe_metrics "cilium-agent:9962" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-agent:9962/proxy/metrics" true true
        probe_metrics "hubble-metrics:9965" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/hubble-metrics:9965/proxy/metrics" true true
        probe_metrics "cilium-envoy:9964" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-envoy:9964/proxy/metrics" true true
        probe_metrics "cilium-operator:9963" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-operator:9963/proxy/metrics" true true
    fi
    if [[ "${ENABLE_DNSPROXY}" == "true" || "${PROVIDER_MANAGED_CILIUM}" != "true" ]]; then
        probe_metrics "cilium-dnsproxy:9967" "/api/v1/namespaces/${DNSPROXY_NAMESPACE}/services/cilium-dnsproxy:9967/proxy/metrics" "${ENABLE_DNSPROXY}" "${ENABLE_DNSPROXY}"
    else
        log "    cilium-dnsproxy metrics: skipped for provider-managed ${DISTRIBUTION}"
    fi
    probe_metrics "tetragon:2112" "/api/v1/namespaces/${TETRAGON_NAMESPACE}/services/tetragon:2112/proxy/metrics"
    probe_metrics "tetragon-operator-metrics:2113" "/api/v1/namespaces/${TETRAGON_NAMESPACE}/services/tetragon-operator-metrics:2113/proxy/metrics"

    log "  Tetragon pod log API (read-only; no container execution or direct credential-payload reads):"
    check_tetragon_pod_logs

    log "  Hubble Timescape discovery (standalone Helm release or cilium-bundled StatefulSet):"
    check_timescape_workloads

    if [[ "${LIVE_FAILURES}" -gt 0 ]]; then
        log "  ERROR: live validation failed with ${LIVE_FAILURES} required check(s) failing."
        exit 1
    fi
    log "  Live validation passed all required checks."
fi
