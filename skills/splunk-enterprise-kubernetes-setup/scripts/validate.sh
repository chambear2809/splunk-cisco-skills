#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-enterprise-k8s-rendered"
TARGET="sok"
OUTPUT_DIR=""
JSON_OUTPUT=false
LIVE=false
STRICT=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Kubernetes Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --target sok|pod          Rendered target to validate (default: sok)
  --output-dir PATH         Render output directory (default: ./splunk-enterprise-k8s-rendered)
  --live                    Run rendered status commands after static checks
  --strict                  Require Helm checks and fail unresolved POD files
  --json                    Emit machine-readable validation result
  --help                    Show this help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) require_arg "$1" $# || exit 1; TARGET="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --strict) STRICT=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

json_array() {
    python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]), end="")
PY
}

json_string() {
    python3 - "$1" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1]), end="")
PY
}

metadata_field() {
    local metadata_file="$1" field="$2"
    python3 - "${metadata_file}" "${field}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
value = payload.get(sys.argv[2], "")
print(value if value is not None else "", end="")
PY
}

run_sok_helm_template_checks() {
    local render_dir="$1"
    local metadata_file="${render_dir}/metadata.json"
    HELM_TEMPLATE_CHECKED=false
    HELM_TEMPLATE_OK=true
    HELM_TEMPLATE_SKIPPED=""

    if ! command -v helm >/dev/null 2>&1; then
        HELM_TEMPLATE_SKIPPED="helm not found"
        return 0
    fi

    HELM_TEMPLATE_CHECKED=true
    local chart_version operator_namespace namespace release_name operator_release_name
    local operator_chart_archive enterprise_chart_archive
    chart_version="$(metadata_field "${metadata_file}" chart_version)"
    operator_namespace="$(metadata_field "${metadata_file}" operator_namespace)"
    namespace="$(metadata_field "${metadata_file}" namespace)"
    release_name="$(metadata_field "${metadata_file}" release_name)"
    operator_release_name="$(metadata_field "${metadata_file}" operator_release_name)"
    operator_chart_archive="$(metadata_field "${metadata_file}" operator_chart_archive)"
    enterprise_chart_archive="$(metadata_field "${metadata_file}" enterprise_chart_archive)"

    local operator_values=(--values operator-values.yaml)
    local enterprise_values=(--values enterprise-values.yaml)
    [[ ! -f "${render_dir}/operator-values-overlay.yaml" ]] || operator_values+=(--values operator-values-overlay.yaml)
    [[ ! -f "${render_dir}/enterprise-values-overlay.yaml" ]] || enterprise_values+=(--values enterprise-values-overlay.yaml)
    local operator_manifest enterprise_manifest chart_dir helm_state
    operator_manifest="$(mktemp)"
    enterprise_manifest="$(mktemp)"
    chart_dir="$(mktemp -d)"
    helm_state="$(mktemp -d)"

    if ! (
        export HELM_REPOSITORY_CONFIG="${helm_state}/repositories.yaml"
        export HELM_REPOSITORY_CACHE="${helm_state}/repository"
        export HELM_CACHE_HOME="${helm_state}/cache"
        export HELM_CONFIG_HOME="${helm_state}/config"
        export HELM_DATA_HOME="${helm_state}/data"
        cd "${render_dir}" || exit 1
        if [[ -n "${operator_chart_archive}" && -n "${enterprise_chart_archive}" ]]; then
            operator_chart="${operator_chart_archive}"
            enterprise_chart="${enterprise_chart_archive}"
        else
            helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update >/dev/null && \
            helm repo update splunk --timeout 2m >/dev/null && \
            helm pull splunk/splunk-operator --version "${chart_version}" --untar --untardir "${chart_dir}" && \
            helm pull splunk/splunk-enterprise --version "${chart_version}" --untar --untardir "${chart_dir}" || exit 1
            operator_chart="${chart_dir}/splunk-operator"
            enterprise_chart="${chart_dir}/splunk-enterprise"
        fi
        # Chart 3.1.0's List templates produce empty-name lint warnings before
        # range expansion for C3/M4. A normal lint still fails template errors;
        # the fully rendered CR checks below validate names and semantics.
        helm lint "${operator_chart}" "${operator_values[@]}" >/dev/null && \
        helm lint "${enterprise_chart}" "${enterprise_values[@]}" >/dev/null && \
        helm template "${operator_release_name}" "${operator_chart}" \
            --namespace "${operator_namespace}" \
            "${operator_values[@]}" >"${operator_manifest}" && \
        helm template "${release_name}" "${enterprise_chart}" \
            --namespace "${namespace}" \
            "${enterprise_values[@]}" >"${enterprise_manifest}"
    ); then
        HELM_TEMPLATE_OK=false
    elif ! python3 - "${metadata_file}" "${operator_manifest}" "${enterprise_manifest}" <<'PY'
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
operator = Path(sys.argv[2]).read_text(encoding="utf-8")
enterprise = Path(sys.argv[3]).read_text(encoding="utf-8")
errors = []

def count_kind(kind):
    return len(re.findall(rf"^\s*kind:\s*{re.escape(kind)}\s*$", enterprise, re.MULTILINE))

def object_blocks(text, wanted_kind):
    """Extract top-level CRs and CRs nested in Helm's kind: List output."""
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)kind:\s*([^\s#]+)\s*$", line)
        if not match or match.group(2) != wanted_kind:
            continue
        kind_indent = len(match.group(1))
        start = index
        while start > 0 and lines[start - 1].strip() and lines[start - 1].strip() != "---":
            previous = lines[start - 1]
            if kind_indent and re.match(r"^-\s+apiVersion:", previous):
                start -= 1
                break
            if not kind_indent and re.match(r"^apiVersion:", previous):
                start -= 1
                break
            start -= 1
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if candidate.strip() == "---":
                break
            if kind_indent and re.match(r"^-\s+apiVersion:", candidate):
                break
            if not kind_indent and re.match(r"^apiVersion:", candidate):
                break
            end += 1
        blocks.append("\n".join(lines[start:end]))
    return blocks

def yaml_scalar_paths(block):
    """Parse scalar paths from Helm's normalized YAML subset."""
    stack = []
    values = []
    for line in block.splitlines():
        match = re.match(
            r"^(\s*)(?:-\s+)?([A-Za-z0-9_.-]+):(?:\s+([^#]+?))?\s*$", line
        )
        if not match:
            sequence = re.match(r"^(\s*)-\s+([^#]+?)\s*$", line)
            if sequence:
                indent = len(sequence.group(1))
                while stack and stack[-1][0] > indent:
                    stack.pop()
                path = tuple(item[1] for item in stack) + ("[]",)
                values.append((path, sequence.group(2).strip().strip('"\'')))
            continue
        indent = len(match.group(1))
        is_sequence_mapping = bool(
            re.match(r"^\s*-\s+[A-Za-z0-9_.-]+:", line)
        )
        key = match.group(2)
        raw = (match.group(3) or "").strip()
        while stack and (
            stack[-1][0] > indent
            or (stack[-1][0] == indent and not is_sequence_mapping)
        ):
            stack.pop()
        path = tuple(item[1] for item in stack) + (key,)
        if raw and raw not in {"|", "|-", "|+", ">", ">-", ">+"}:
            values.append((path, raw.strip('"\'')))
        else:
            stack.append((indent, key))
    return values

def path_values(block, suffix):
    return [
        value
        for path, value in yaml_scalar_paths(block)
        if len(path) >= len(suffix) and path[-len(suffix):] == suffix
    ]

def path_scalar(block, suffix):
    values = path_values(block, suffix)
    return values[0] if len(values) == 1 else None

def container_env(block):
    pairs = {}
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)-\s+name:\s*([^\s#]+)\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        name = match.group(2).strip('"\'')
        for nested in lines[index + 1:]:
            nested_indent = len(nested) - len(nested.lstrip())
            if nested.strip() and nested_indent <= indent:
                break
            value = re.match(r"^\s*value:\s*([^#]+?)\s*$", nested)
            if value:
                pairs[name] = value.group(1).strip().strip('"\'')
                break
    return pairs

SENSITIVE_NAME = re.compile(
    r"(?:password|passphrase|token|secret|credential|auth|accesskey|apikey|"
    r"clientkey|privatekey|hectoken)$",
    re.IGNORECASE,
)
REFERENCE_SUFFIXES = (
    "secretkeyref", "secretref", "secretname", "valuefrom",
)

def check_sensitive_literals(block, identity):
    """Reject literal credentials after Helm has normalized an overlay."""
    signatures = (
        re.compile(
            r"-----BEGIN (?:ENCRYPTED |RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA|ASCA)[A-Z0-9]{16}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{12,}\b"),
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    )
    if any(pattern.search(block) for pattern in signatures):
        errors.append(f"{identity} contains credential or private-key material")
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = re.match(
            r"^(\s*)(?:-\s+)?([A-Za-z0-9_.-]+):(?:\s+(.*?))?\s*$", line
        )
        if not match:
            continue
        indent = len(match.group(1))
        key = match.group(2)
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        raw = (match.group(3) or "").split("#", 1)[0].strip()
        scalar = raw.strip('"\'')
        parsed = urlsplit(scalar)
        if parsed.scheme and parsed.netloc and (
            parsed.username is not None or parsed.password is not None
        ):
            errors.append(f"{identity} embeds URL userinfo credentials at {key}")
        if normalized == "secret" and raw == "":
            allowed = {"defaultmode", "items", "key", "mode", "optional", "path", "secretname"}
            nested_keys = []
            for nested in lines[index + 1:]:
                nested_text = nested.strip()
                if not nested_text or nested_text.startswith("#"):
                    continue
                nested_indent = len(nested) - len(nested.lstrip())
                if nested_indent <= indent:
                    break
                nested_match = re.match(
                    r"^(?:-\s+)?([A-Za-z0-9_.-]+):", nested_text
                )
                if nested_match:
                    nested_keys.append(
                        re.sub(r"[^a-z0-9]", "", nested_match.group(1).lower())
                    )
            if "secretname" in nested_keys and set(nested_keys) <= allowed:
                continue
        if normalized.endswith(REFERENCE_SUFFIXES) or not SENSITIVE_NAME.search(normalized):
            continue
        if raw not in {"", '""', "''", "null", "~"}:
            errors.append(f"{identity} contains literal sensitive field {key}")
            continue
        if raw:
            continue
        for nested in lines[index + 1:]:
            nested_text = nested.strip()
            if not nested_text or nested_text.startswith("#"):
                continue
            nested_indent = len(nested) - len(nested.lstrip())
            if nested_indent > indent:
                errors.append(
                    f"{identity} contains nested sensitive field {key}"
                )
            break

def reference_identity(block, field):
    return {
        part: path_scalar(block, ("spec", field, part)) or ""
        for part in (
            "apiVersion", "fieldPath", "kind", "name", "namespace",
            "resourceVersion", "uid",
        )
    }

def resource_values(block, prefix=("spec", "resources")):
    return {
        section: {
            resource: path_scalar(
                block, prefix + (section, resource)
            )
            for resource in ("cpu", "memory")
            if path_scalar(block, ("spec", "resources", section, resource))
        }
        for section in ("requests", "limits")
    }

def has_exact_zone_affinity(block, field, zone):
    prefix = ("spec", field)
    if field == "affinity":
        prefix += ("nodeAffinity",)
    selector = prefix + (
        "requiredDuringSchedulingIgnoredDuringExecution",
        "nodeSelectorTerms",
        "matchExpressions",
    )
    return (
        path_values(block, selector + ("key",)) == ["topology.kubernetes.io/zone"]
        and path_values(block, selector + ("operator",)) == ["In"]
        and path_values(block, selector + ("values", "[]")) == [zone]
    )

architecture = metadata.get("architecture")
if architecture == "s1":
    expected_names = {"Standalone": {"s1"}}
else:
    indexer_names = (
        {f"idxc-site{index}" for index in range(1, metadata.get("site_count", 1) + 1)}
        if architecture == "m4"
        else {"idxc"}
    )
    expected_names = {
        "ClusterManager": {"cm"},
        "IndexerCluster": indexer_names,
        "SearchHeadCluster": {"shc"},
    }
expected_names["LicenseManager"] = {"lm"} if metadata.get("local_license_manager") else set()
expected_names["MonitoringConsole"] = {"mc"} if metadata.get("monitoring_console") else set()
expected_names["Queue"] = {"ingest-queue"} if metadata.get("indexing_ingestion_separation") else set()
expected_names["ObjectStorage"] = {"ingest-object-storage"} if metadata.get("indexing_ingestion_separation") else set()
expected_names["IngestorCluster"] = {"ingestor"} if metadata.get("indexing_ingestion_separation") else set()
expected = {kind: len(names) for kind, names in expected_names.items()}
for kind, count in expected.items():
    actual = count_kind(kind)
    if actual != count:
        errors.append(f"expected {count} {kind} object(s), rendered {actual}")
    blocks = object_blocks(enterprise, kind)
    rendered_names = {
        path_scalar(block, ("metadata", "name")) for block in blocks
    }
    if rendered_names != expected_names[kind]:
        errors.append(
            f"{kind} names changed from {sorted(expected_names[kind])} "
            f"to {sorted(map(str, rendered_names))}"
        )
    for block in blocks:
        if path_scalar(block, ("metadata", "namespace")) != metadata.get("namespace"):
            errors.append(f"{kind} rendered outside the reviewed namespace")

allowed_enterprise_kinds = {"List", *expected_names}
rendered_enterprise_kinds = set(
    re.findall(r"^\s*kind:\s*([^\s#]+)\s*$", enterprise, re.MULTILINE)
)
unexpected_kinds = rendered_enterprise_kinds - allowed_enterprise_kinds
if unexpected_kinds:
    errors.append(f"Enterprise overlay rendered unexpected kinds: {sorted(unexpected_kinds)}")

expected_splunk_image = metadata.get("splunk_image")
for kind in ("Standalone", "ClusterManager", "IndexerCluster", "SearchHeadCluster", "LicenseManager", "MonitoringConsole", "IngestorCluster"):
    for block in object_blocks(enterprise, kind):
        if path_scalar(block, ("spec", "image")) != expected_splunk_image:
            errors.append(f"{kind} image differs from reviewed metadata")
        if path_scalar(block, ("spec", "imagePullPolicy")) != "IfNotPresent":
            errors.append(f"{kind} imagePullPolicy differs from reviewed metadata")

workload_kinds = [
    kind
    for kind, count in expected.items()
    if count and kind not in {"Queue", "ObjectStorage"}
]
for kind, names in expected_names.items():
    for block in object_blocks(enterprise, kind):
        identity = f"{kind}/{path_scalar(block, ('metadata', 'name')) or 'unknown'}"
        check_sensitive_literals(block, identity)
        for env_name, env_value in container_env(block).items():
            normalized_env_name = re.sub(r"[^a-z0-9]", "", env_name.lower())
            if SENSITIVE_NAME.search(normalized_env_name):
                errors.append(
                    f"{identity} contains literal sensitive environment variable "
                    f"{env_name}"
                )
for kind in workload_kinds:
    expected_service_account = (
        metadata.get("splunk_service_account")
        if kind in {"Standalone", "IndexerCluster"}
        else None
    )
    if metadata.get("indexing_ingestion_separation") and kind in {
        "ClusterManager", "IndexerCluster", "IngestorCluster",
    }:
        expected_service_account = metadata.get("ingestor_service_account")
    for block in object_blocks(enterprise, kind):
        if (path_scalar(block, ("spec", "serviceAccount")) or None) != (
            expected_service_account or None
        ):
            errors.append(f"{kind} serviceAccount differs from reviewed metadata")

expected_operator_image = metadata.get("operator_image")
operator_images = {
    match.strip('"\'')
    for match in re.findall(r"^\s*image:\s*([^\s#]+)", operator, re.MULTILINE)
}
if expected_operator_image not in operator_images:
    errors.append("operator image differs from reviewed metadata")
operator_deployments = object_blocks(operator, "Deployment")
environment = {}
if len(operator_deployments) != 1:
    errors.append("operator chart must render exactly one Deployment")
else:
    operator_deployment = operator_deployments[0]
    if path_scalar(operator_deployment, ("metadata", "name")) != "splunk-operator-controller-manager":
        errors.append("operator Deployment name differs from the supported chart identity")
    if path_scalar(operator_deployment, ("metadata", "namespace")) != metadata.get("operator_namespace"):
        errors.append("operator Deployment rendered outside the reviewed namespace")
    if expected_operator_image not in path_values(
        operator_deployment, ("containers", "image")
    ):
        errors.append("operator Deployment image differs from reviewed metadata")
    if path_scalar(operator_deployment, ("containers", "imagePullPolicy")) != "IfNotPresent":
        errors.append("operator imagePullPolicy differs from reviewed metadata")
    environment = container_env(operator_deployment)
    for env_name in environment:
        normalized_env_name = re.sub(r"[^a-z0-9]", "", env_name.lower())
        if SENSITIVE_NAME.search(normalized_env_name):
            errors.append(
                "operator Deployment contains literal sensitive environment "
                f"variable {env_name}"
            )
    if environment.get("RELATED_IMAGE_SPLUNK_ENTERPRISE") != expected_splunk_image:
        errors.append("operator related Splunk image differs from reviewed metadata")
    if metadata.get("terms_accepted") and environment.get("SPLUNK_GENERAL_TERMS") != "--accept-sgt-current-at-splunk-com":
        errors.append("operator manifest lost the reviewed Splunk General Terms setting")
    app_staging_mount = re.search(
        r"^\s*-\s+mountPath:\s*/opt/splunk/appframework/\s*\n\s+name:\s*app-staging\s*$",
        operator_deployment,
        re.MULTILINE,
    )
    app_staging_volume = re.search(
        r"^\s*-\s+name:\s*app-staging\s*\n\s+persistentVolumeClaim:\s*\n\s+claimName:\s*splunk-operator-app-download\s*$",
        operator_deployment,
        re.MULTILINE,
    )
    if not app_staging_mount or not app_staging_volume:
        errors.append("operator App Framework staging PVC mount was removed or changed")
app_staging_claims = object_blocks(operator, "PersistentVolumeClaim")
if len(app_staging_claims) != 1:
    errors.append("operator chart must render exactly one App Framework staging PVC")
else:
    claim = app_staging_claims[0]
    if path_scalar(claim, ("metadata", "name")) != "splunk-operator-app-download":
        errors.append("operator App Framework staging PVC name differs from chart contract")
    if path_scalar(claim, ("metadata", "namespace")) != metadata.get("operator_namespace"):
        errors.append("operator App Framework staging PVC rendered outside reviewed namespace")
    if (path_scalar(claim, ("spec", "storageClassName")) or "") != (
        metadata.get("storage_class") or ""
    ):
        errors.append("operator App Framework staging PVC StorageClass differs from reviewed metadata")
    if path_values(claim, ("spec", "accessModes", "[]")) != ["ReadWriteOnce"]:
        errors.append("operator App Framework staging PVC access mode differs from chart contract")
    if path_scalar(claim, ("spec", "resources", "requests", "storage")) != "10Gi":
        errors.append("operator App Framework staging PVC capacity differs from chart contract")
    if path_scalar(claim, ("spec", "volumeMode")) != "Filesystem":
        errors.append("operator App Framework staging PVC volume mode differs from chart contract")
if re.search(r"^\s*kind:\s*Secret\s*$", operator + "\n" + enterprise, re.MULTILINE):
    errors.append("values overlays must not render Kubernetes Secret objects")

replica_expectations = {}
if architecture == "s1":
    replica_expectations["Standalone"] = metadata.get("standalone_replicas")
else:
    replica_expectations["IndexerCluster"] = metadata.get("indexer_replicas")
    replica_expectations["SearchHeadCluster"] = metadata.get("search_head_replicas")
if metadata.get("indexing_ingestion_separation"):
    replica_expectations["IngestorCluster"] = metadata.get("ingestor_replicas")
for kind, replica_count in replica_expectations.items():
    for block in object_blocks(enterprise, kind):
        rendered_replicas = path_scalar(block, ("spec", "replicas"))
        if rendered_replicas != str(replica_count):
            errors.append(
                f"{kind} replicas changed from requested {replica_count} to {rendered_replicas}"
            )

for kind in workload_kinds:
    for block in object_blocks(enterprise, kind):
        for field, capacity in (
            ("etcVolumeStorageConfig", metadata.get("etc_storage")),
            ("varVolumeStorageConfig", metadata.get("var_storage")),
        ):
            if path_scalar(block, ("spec", field, "ephemeralStorage")) != "false":
                errors.append(f"{kind} {field} must remain persistent")
            if path_scalar(block, ("spec", field, "storageCapacity")) != capacity:
                errors.append(f"{kind} {field} capacity differs from reviewed metadata")
            rendered_class = path_scalar(block, ("spec", field, "storageClassName")) or ""
            expected_class = metadata.get("storage_class") or ""
            if rendered_class != expected_class:
                errors.append(f"{kind} {field} StorageClass differs from reviewed metadata")

license_file_name = metadata.get("license_file_name")
local_license_kind = "Standalone" if architecture == "s1" else "LicenseManager"
if license_file_name:
    local_blocks = object_blocks(enterprise, local_license_kind)
    if len(local_blocks) != 1:
        errors.append(f"local license requires exactly one {local_license_kind}")
    else:
        local = local_blocks[0]
        if path_scalar(local, ("spec", "licenseUrl")) != f"/mnt/licenses/{license_file_name}":
            errors.append("local license URL differs from reviewed metadata")
        license_volume = re.search(
            r"^\s*-\s+configMap:\s*\n\s+name:\s*splunk-licenses\s*\n\s+name:\s*licenses\s*$",
            local,
            re.MULTILINE,
        )
        if not license_volume:
            errors.append("local license ConfigMap/volume identity differs from reviewed metadata")

expected_license_name = metadata.get("existing_license_manager")
expected_license_namespace = metadata.get("existing_license_manager_namespace")
if metadata.get("local_license_manager"):
    expected_license_name = "lm"
    expected_license_namespace = metadata.get("namespace")
rendered_license_namespace = (
    expected_license_namespace
    if expected_license_namespace and expected_license_namespace != metadata.get("namespace")
    else ""
)
for kind in workload_kinds:
    if kind == "LicenseManager" or (architecture == "s1" and license_file_name):
        continue
    for block in object_blocks(enterprise, kind):
        actual_reference = reference_identity(block, "licenseManagerRef")
        expected_reference = {
            "apiVersion": "", "fieldPath": "", "kind": "",
            "name": expected_license_name or "",
            "namespace": rendered_license_namespace if expected_license_name else "",
            "resourceVersion": "", "uid": "",
        }
        if actual_reference != expected_reference:
            errors.append(f"{kind} LicenseManager reference differs from reviewed metadata")

cluster_manager_ref_kinds = {
    "LicenseManager", "IndexerCluster", "SearchHeadCluster", "MonitoringConsole"
}
for kind in workload_kinds:
    for block in object_blocks(enterprise, kind):
        expected_cluster_manager = (
            "cm" if architecture in {"c3", "m4"} and kind in cluster_manager_ref_kinds else None
        )
        actual_cluster_manager = reference_identity(block, "clusterManagerRef")
        expected_cluster_manager_reference = {
            "apiVersion": "", "fieldPath": "", "kind": "",
            "name": expected_cluster_manager or "", "namespace": "",
            "resourceVersion": "", "uid": "",
        }
        if actual_cluster_manager != expected_cluster_manager_reference:
            errors.append(f"{kind} ClusterManager reference differs from reviewed topology")
        expected_monitoring_console = (
            "mc" if metadata.get("monitoring_console") and kind != "MonitoringConsole" else None
        )
        actual_monitoring_console = reference_identity(block, "monitoringConsoleRef")
        expected_monitoring_console_reference = {
            "apiVersion": "", "fieldPath": "", "kind": "",
            "name": expected_monitoring_console or "", "namespace": "",
            "resourceVersion": "", "uid": "",
        }
        if actual_monitoring_console != expected_monitoring_console_reference:
            errors.append(f"{kind} MonitoringConsole reference differs from reviewed topology")

smartstore_kind = "Standalone" if architecture == "s1" else "ClusterManager"
smartstore_blocks = object_blocks(enterprise, smartstore_kind)
if metadata.get("smartstore_path"):
    if len(smartstore_blocks) != 1:
        errors.append("SmartStore owner CR is missing or ambiguous")
    else:
        smartstore = smartstore_blocks[0]
        checks = {
            ("spec", "smartstore", "defaults", "volumeName"): "remote_store",
            ("spec", "smartstore", "volumes", "name"): "remote_store",
            ("spec", "smartstore", "volumes", "storageType"): "s3",
            ("spec", "smartstore", "volumes", "provider"): metadata.get("smartstore_provider"),
            ("spec", "smartstore", "volumes", "path"): metadata.get("smartstore_path"),
            ("spec", "smartstore", "volumes", "endpoint"): metadata.get("smartstore_endpoint"),
            ("spec", "smartstore", "volumes", "region"): metadata.get("smartstore_region") or "",
            ("spec", "smartstore", "volumes", "secretRef"): metadata.get("smartstore_secret_ref"),
        }
        for path, wanted in checks.items():
            if path_scalar(smartstore, path) != wanted:
                errors.append(f"SmartStore {path[-1]} differs from reviewed metadata")
        expected_indexes = metadata.get("smartstore_indexes", [])
        if path_values(smartstore, ("spec", "smartstore", "indexes", "name")) != expected_indexes:
            errors.append("SmartStore index inventory/order differs from reviewed metadata")
        if path_values(smartstore, ("spec", "smartstore", "indexes", "remotePath")) != ["$_index_name"] * len(expected_indexes):
            errors.append("SmartStore index remotePath contract differs from reviewed metadata")
        if path_values(smartstore, ("spec", "smartstore", "indexes", "volumeName")) != ["remote_store"] * len(expected_indexes):
            errors.append("SmartStore index volume binding differs from reviewed metadata")
elif smartstore_blocks and path_values(
    smartstore_blocks[0], ("spec", "smartstore", "volumes", "name")
):
    errors.append("manifest gained unreviewed SmartStore volumes")

if metadata.get("deployment_profile") == "production":
    if metadata.get("smartstore_index_inventory_confirmed") is not True:
        errors.append("production SmartStore index inventory is not attested")
    if metadata.get("smartstore_path_ownership_confirmed") is not True:
        errors.append("production SmartStore path ownership is not attested")

    def guaranteed(resources):
        complete = all(
            set(resources[section]) == {"cpu", "memory"}
            for section in ("requests", "limits")
        )
        quantities = [
            value
            for section in ("requests", "limits")
            for value in resources[section].values()
        ]
        valid_quantities = all(
            re.fullmatch(
                r"(?:[1-9][0-9]*(?:\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)(?:m|[KMGTPE]i?)?",
                value,
            )
            for value in quantities
        )
        return complete and valid_quantities and resources["requests"] == resources["limits"]

    for kind in workload_kinds:
        for block in object_blocks(enterprise, kind):
            resources = resource_values(block)
            if not guaranteed(resources):
                errors.append(f"production {kind} does not have Guaranteed QoS resources")
            if kind == "SearchHeadCluster" and not guaranteed(
                resource_values(block, ("spec", "deployerResourceSpec"))
            ):
                errors.append("production SearchHeadCluster deployer lacks Guaranteed QoS resources")

if metadata.get("indexing_ingestion_separation"):
    for kind in ("Queue", "ObjectStorage", "IngestorCluster"):
        if count_kind(kind) != 1:
            errors.append(f"expected one {kind} for separated ingestion")
    queue_blocks = object_blocks(enterprise, "Queue")
    if queue_blocks:
        queue_checks = {
            ("spec", "provider"): metadata.get("queue_provider"),
            ("spec", "sqs", "name"): metadata.get("queue_name"),
            ("spec", "sqs", "authRegion"): metadata.get("queue_region"),
            ("spec", "sqs", "endpoint"): metadata.get("queue_endpoint"),
            ("spec", "sqs", "dlq"): metadata.get("queue_dlq"),
        }
        for path, wanted in queue_checks.items():
            if path_scalar(queue_blocks[0], path) != wanted:
                errors.append(f"Queue {path[-1]} differs from reviewed metadata")
    object_blocks_rendered = object_blocks(enterprise, "ObjectStorage")
    if object_blocks_rendered:
        object_checks = {
            ("spec", "provider"): "s3",
            ("spec", "s3", "path"): metadata.get("object_storage_path"),
            ("spec", "s3", "endpoint"): metadata.get("object_storage_endpoint"),
        }
        for path, wanted in object_checks.items():
            if path_scalar(object_blocks_rendered[0], path) != wanted:
                errors.append(f"ObjectStorage {path[-1]} differs from reviewed metadata")
    for kind in ("IndexerCluster", "IngestorCluster"):
        for block in object_blocks(enterprise, kind):
            queue_reference = reference_identity(block, "queueRef")
            object_reference = reference_identity(block, "objectStorageRef")
            expected_queue_reference = {
                "apiVersion": "", "fieldPath": "", "kind": "",
                "name": "ingest-queue", "namespace": "",
                "resourceVersion": "", "uid": "",
            }
            expected_object_reference = {
                "apiVersion": "", "fieldPath": "", "kind": "",
                "name": "ingest-object-storage", "namespace": "",
                "resourceVersion": "", "uid": "",
            }
            if (
                queue_reference != expected_queue_reference
                or object_reference != expected_object_reference
            ):
                errors.append(f"{kind} is missing Queue/ObjectStorage references")
    identity = metadata.get("ingestor_service_account")
    for kind in ("ClusterManager", "IndexerCluster", "IngestorCluster"):
        for block in object_blocks(enterprise, kind):
            if (path_scalar(block, ("spec", "serviceAccount")) or None) != (
                identity or None
            ):
                errors.append(f"{kind} is missing the separated-tier service account")
    if metadata.get("queue_secret_workaround"):
        if not queue_blocks or path_values(
            queue_blocks[0], ("spec", "sqs", "volumes", "secretRef")
        ) != [metadata.get("queue_secret_ref")]:
            errors.append("Queue credential volume was not rendered")
        if re.search(r"volumes:\s*\n\s+authRegion:", enterprise):
            errors.append("Queue credential volume triggered the chart 3.1 serialization defect")

if "kind: ClusterMaster" in enterprise or "kind: LicenseMaster" in enterprise:
    errors.append("legacy v3 Manager terminology was rendered")
if "kind: Deployment" not in operator:
    errors.append("operator chart did not render its Deployment")
if metadata.get("deployment_profile") == "production":
    if architecture == "m4":
        manager_blocks = object_blocks(enterprise, "ClusterManager")
        if not manager_blocks or not has_exact_zone_affinity(
            manager_blocks[0], "affinity", metadata.get("manager_zone")
        ):
            errors.append("M4 Cluster Manager zone affinity differs from reviewed metadata")
        if manager_blocks and path_scalar(
            manager_blocks[0], ("spec", "defaults", "splunk", "site")
        ) != metadata.get("manager_site"):
            errors.append("M4 Cluster Manager Splunk site differs from reviewed metadata")
        if manager_blocks:
            manager_defaults = {
                key: path_scalar(
                    manager_blocks[0], ("spec", "defaults", "splunk", key)
                )
                for key in (
                    "all_sites",
                    "multisite_replication_factor_origin",
                    "multisite_replication_factor_total",
                    "multisite_search_factor_origin",
                    "multisite_search_factor_total",
                )
            }
            expected_defaults = {
                "all_sites": ",".join(
                    f"site{index}" for index in range(1, metadata.get("site_count", 1) + 1)
                ),
                "multisite_replication_factor_origin": "1",
                "multisite_replication_factor_total": "2",
                "multisite_search_factor_origin": "1",
                "multisite_search_factor_total": "2",
            }
            if manager_defaults != expected_defaults:
                errors.append("M4 multisite replication/search contract differs from reviewed metadata")
        expected_indexer_zones = {
            f"idxc-site{index}": zone
            for index, zone in enumerate(metadata.get("site_zones", []), 1)
        }
        for block in object_blocks(enterprise, "IndexerCluster"):
            name = path_scalar(block, ("metadata", "name"))
            if not has_exact_zone_affinity(
                block, "affinity", expected_indexer_zones.get(name)
            ):
                errors.append(f"M4 {name} zone affinity differs from reviewed metadata")
            expected_site = name.removeprefix("idxc-") if name else None
            if path_scalar(
                block, ("spec", "defaults", "splunk", "site")
            ) != expected_site:
                errors.append(f"M4 {name} Splunk site differs from its reviewed identity")
        search_blocks = object_blocks(enterprise, "SearchHeadCluster")
        if not search_blocks:
            errors.append("M4 Search Head deployer has no required zone affinity")
        else:
            search_zone = metadata.get("search_head_zone")
            if not has_exact_zone_affinity(
                search_blocks[0], "affinity", search_zone
            ) or not has_exact_zone_affinity(
                search_blocks[0], "deployerNodeAffinity", search_zone
            ):
                errors.append("M4 Search Head member/deployer zones differ from reviewed metadata")
            if path_scalar(
                search_blocks[0], ("spec", "defaults", "splunk", "site")
            ) != metadata.get("search_head_site"):
                errors.append("M4 Search Head Splunk site differs from reviewed metadata")
        for kind in ("LicenseManager", "MonitoringConsole"):
            for block in object_blocks(enterprise, kind):
                if not has_exact_zone_affinity(
                    block, "affinity", metadata.get("manager_zone")
                ):
                    errors.append(f"M4 {kind} has no management-zone affinity")

if metadata.get("operator_scope") == "cluster":
    if not re.search(r"^kind:\s*ClusterRole\s*$", operator, re.MULTILINE) or not re.search(
        r"^kind:\s*ClusterRoleBinding\s*$", operator, re.MULTILINE
    ):
        errors.append("cluster-scoped operator RBAC was not rendered")
else:
    if re.search(r"^kind:\s*ClusterRole(?:Binding)?\s*$", operator, re.MULTILINE):
        errors.append("namespace-scoped operator unexpectedly rendered cluster-wide RBAC")
    if not re.search(r"^kind:\s*Role\s*$", operator, re.MULTILINE) or not re.search(
        r"^kind:\s*RoleBinding\s*$", operator, re.MULTILINE
    ):
        errors.append("namespace-scoped operator RBAC was not rendered")
expected_watch_namespaces = ",".join(metadata.get("watch_namespaces", []))
if environment.get("WATCH_NAMESPACE") != expected_watch_namespaces:
    errors.append("operator WATCH_NAMESPACE differs from reviewed metadata")

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
    then
        HELM_TEMPLATE_OK=false
    fi
    rm -f "${operator_manifest}" "${enterprise_manifest}"
    rm -rf "${chart_dir}" "${helm_state}"
}

run_shell_syntax_checks() {
    local render_dir="$1" script
    SHELL_SYNTAX_OK=true
    PYTHON_SYNTAX_OK=true
    while IFS= read -r -d '' script; do
        if [[ ! -x "${script}" ]] || ! bash -n "${script}"; then
            SHELL_SYNTAX_OK=false
        fi
    done < <(find "${render_dir}" -maxdepth 1 -type f -name '*.sh' -print0)
    while IFS= read -r -d '' script; do
        if ! python3 - "${script}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
        then
            PYTHON_SYNTAX_OK=false
        fi
    done < <(find "${render_dir}" -maxdepth 1 -type f -name '*.py' -print0)
}

run_bundle_integrity_check() {
    local render_dir="$1"
    BUNDLE_INTEGRITY_OK=true
    if ! python3 "${SCRIPT_DIR}/bundle_verify.py" verify "${render_dir}" "${TARGET}"; then
        BUNDLE_INTEGRITY_OK=false
    fi
}

run_pod_config_checks() {
    local render_dir="$1"
    POD_CONFIG_OK=true
    POD_ARTIFACTS_CHECKED=false
    POD_ARTIFACTS_OK=true
    if ! python3 - "${render_dir}/cluster-config.yaml" "${render_dir}/metadata.json" "${STRICT}" <<'PY'
import hashlib
import ipaddress
import json
import re
import stat
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
metadata_path = Path(sys.argv[2])
strict = sys.argv[3] == "true"
text = config_path.read_text(encoding="utf-8")
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
errors = []

def top_section(name):
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line == f"{name}:"), None)
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^[a-z][a-zA-Z]*:", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])

if "apiVersion: enterprise.splunk.com/v1beta1" not in text:
    errors.append("unexpected or missing POD apiVersion")
if "kind: KubernetesCluster" not in text:
    errors.append("missing KubernetesCluster kind")
profile_match = re.search(r"^profile:\s*([^\s#]+)", text, re.MULTILINE)
if not profile_match or profile_match.group(1) != metadata.get("pod_base_profile"):
    errors.append("profile does not match metadata")

sections = {"controllers": [], "workers": []}
private_networks = tuple(
    ipaddress.IPv4Network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
section = None
for line in text.splitlines():
    top = re.match(r"^([a-z][a-zA-Z]*):", line)
    if top:
        section = top.group(1) if top.group(1) in sections else None
        continue
    match = re.match(r'^\s+-\s+address:\s*("(?:[^"\\]|\\.)*"|[^\s#]+)', line)
    if section in sections and match:
        raw = match.group(1)
        value = json.loads(raw) if raw.startswith('"') else raw
        try:
            parsed = ipaddress.IPv4Address(value)
        except ValueError:
            errors.append(f"invalid IPv4 {section} address: {value}")
        else:
            if (
                parsed.is_unspecified
                or parsed.is_loopback
                or parsed.is_link_local
                or parsed.is_multicast
                or parsed.is_reserved
                or int(parsed) == 0xFFFFFFFF
                or not (
                    parsed.is_global
                    or any(parsed in network for network in private_networks)
                )
            ):
                errors.append(f"non-unicast IPv4 {section} address: {value}")
        sections[section].append(value)

if len(sections["controllers"]) != metadata.get("controller_count"):
    errors.append("controller count does not match metadata")
if len(sections["workers"]) != metadata.get("worker_count"):
    errors.append("worker count does not match metadata")
all_addresses = sections["controllers"] + sections["workers"]
if len(all_addresses) != len(set(all_addresses)):
    errors.append("controller and worker addresses must be unique")

names = re.findall(r'^\s+-\s+name:\s*("(?:[^"\\]|\\.)*"|[^\s#]+)', text, re.MULTILINE)
decoded_names = [json.loads(item) if item.startswith('"') else item for item in names]
if len(decoded_names) != len(set(decoded_names)):
    errors.append("search-tier names must be unique")
product_profile = metadata.get("pod_profile", "").endswith(("-es", "-itsi"))
expected_search_tiers = 2 if product_profile else 1
if len(decoded_names) != expected_search_tiers:
    errors.append(f"expected {expected_search_tiers} named search tier(s)")
if metadata.get("pod_base_profile") == "pod-small":
    if "\nstandalone:\n" not in text or "\nsearchheadcluster:\n" in text:
        errors.append("pod-small must use standalone search tiers")
elif "\nsearchheadcluster:\n" not in text or "\nstandalone:\n" in text:
    errors.append("POD Medium/Large/X-Large must use searchheadcluster tiers")
if metadata.get("pod_profile", "").endswith("-es") and "premium:" not in text:
    errors.append("ES profile is missing premium app scope")
if not metadata.get("pod_profile", "").endswith("-es") and "premium:" in text:
    errors.append("premium app scope is valid only for ES profiles")

if strict:
    markers = ("/path/to/", "./path/to/", "./apps/")
    if any(marker in text for marker in markers):
        errors.append("placeholder paths remain in the POD configuration")
    reviewed_installer = metadata.get("reviewed_installer_bundle_path")
    if reviewed_installer:
        if reviewed_installer != "kubernetes-installer-reviewed":
            errors.append("reviewed POD installer bundle path is not canonical")
        installer = metadata_path.parent / reviewed_installer
        if installer.is_symlink() or not installer.is_file():
            errors.append("reviewed POD installer snapshot is missing or unsafe")
        elif stat.S_IMODE(installer.stat().st_mode) != 0o500:
            errors.append("reviewed POD installer snapshot must have mode 0500")
        else:
            digest = hashlib.sha256()
            with installer.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != metadata.get("installer_sha256"):
                errors.append("reviewed POD installer snapshot digest differs")
    else:
        installer = Path(metadata.get("installer_path", "")).expanduser()
        if not installer.is_file() or not installer.stat().st_mode & 0o111:
            errors.append("POD installer is missing or not executable")
    if metadata.get("pod_profile", "").endswith("-es"):
        premium_match = re.search(r"^\s+premium:\s*\n(\s+-\s+.+)", text, re.MULTILINE)
        if not premium_match:
            errors.append("ES premium app package is missing")
    if metadata.get("pod_profile", "").endswith("-itsi"):
        license_files = metadata.get("license_files", [])
        if len(license_files) < 2 or len(set(license_files)) != len(license_files):
            errors.append("ITSI requires distinct Enterprise and ITSI license files")
    for raw in re.findall(r'^\s*privateKey:\s*("[^"\n]+")', text, re.MULTILINE):
        value = json.loads(raw)
        private_key = Path(value).expanduser()
        if not private_key.is_file():
            errors.append(f"referenced private key is missing: {value}")
        elif stat.S_IMODE(private_key.stat().st_mode) & 0o077:
            errors.append(f"private key permissions are too broad: {value}")
    path_values = re.findall(r'"(?:[^"\\]|\\.)*"', text)
    for raw in path_values:
        value = json.loads(raw)
        if value.startswith(("/", "./", "../", "~/")) and not Path(value).expanduser().is_file():
            errors.append(f"referenced local file is missing: {value}")
    app_sections = "\n".join(
        top_section(name)
        for name in ("clustermanager", "licensemanager", "standalone", "searchheadcluster")
    )
    for raw in re.findall(r'"(?:[^"\\]|\\.)*"', app_sections):
        value = json.loads(raw)
        if value.startswith(("/", "./", "../", "~/")) and not value.lower().endswith(
            (".spl", ".tgz", ".tar.gz")
        ):
            errors.append(f"unsupported POD app archive extension: {value}")

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
    then
        POD_CONFIG_OK=false
    fi
    if [[ "${POD_CONFIG_OK}" == "true" && "${STRICT}" == "true" ]]; then
        POD_ARTIFACTS_CHECKED=true
        if ! (cd "${render_dir}" && python3 pod-artifacts.py metadata.json >/dev/null); then
            POD_ARTIFACTS_OK=false
            POD_CONFIG_OK=false
        fi
    fi
}

main() {
    command -v python3 >/dev/null || { log "ERROR: Python 3.9+ is required."; exit 1; }
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else "ERROR: Python 3.9+ is required.")'
    validate_choice "${TARGET}" sok pod
    if [[ "${LIVE}" == "true" ]]; then
        STRICT=true
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        if [[ -L "${OUTPUT_DIR}" ]]; then
            log "ERROR: --output-dir must not be a symbolic link: ${OUTPUT_DIR}"
            exit 1
        fi
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi

    local render_dir="${OUTPUT_DIR}/${TARGET}"
    if [[ -L "${render_dir}" ]]; then
        log "ERROR: Render target must not be a symbolic link: ${render_dir}"
        exit 1
    fi
    local missing=()
    local required=()
    if [[ "${TARGET}" == "sok" ]]; then
        required=(
            README.md
            metadata.json
            bundle-manifest.json
            namespace.yaml
            apply.sh
            bundle-verify.py
            crds-install.sh
            preflight.sh
            server-dry-run.sh
            operator-values.yaml
            enterprise-values.yaml
            helm-install-operator.sh
            helm-install-enterprise.sh
            compatibility-check.py
            verify-cluster.sh
            status.sh
        )
    else
        required=(
            README.md
            metadata.json
            bundle-manifest.json
            cluster-config.yaml
            preflight.sh
            deploy.sh
            status-workers.sh
            status.sh
            get-creds.sh
            web-docs.sh
            wait-ready.sh
            diagnostics.sh
            pod-artifacts.py
            pod-inputs.py
            bundle-verify.py
        )
    fi

    local file
    for file in "${required[@]}"; do
        if [[ ! -f "${render_dir}/${file}" ]]; then
            missing+=("${file}")
        fi
    done

    local ok=true
    if (( ${#missing[@]} > 0 )); then
        ok=false
    fi

    SHELL_SYNTAX_OK=true
    PYTHON_SYNTAX_OK=true
    POD_CONFIG_OK=true
    POD_ARTIFACTS_CHECKED=false
    POD_ARTIFACTS_OK=true
    BUNDLE_INTEGRITY_OK=true
    if [[ "${ok}" == "true" ]]; then
        run_bundle_integrity_check "${render_dir}" "${required[@]}"
        if [[ "${BUNDLE_INTEGRITY_OK}" != "true" ]]; then
            ok=false
        fi
        run_shell_syntax_checks "${render_dir}"
        if [[ "${SHELL_SYNTAX_OK}" != "true" ]]; then
            ok=false
        fi
        if [[ "${PYTHON_SYNTAX_OK}" != "true" ]]; then
            ok=false
        fi
        if [[ "${TARGET}" == "pod" ]]; then
            run_pod_config_checks "${render_dir}"
            if [[ "${POD_CONFIG_OK}" != "true" ]]; then
                ok=false
            fi
        fi
    fi

    HELM_TEMPLATE_CHECKED=false
    HELM_TEMPLATE_OK=true
    HELM_TEMPLATE_SKIPPED=""
    if [[ "${TARGET}" == "sok" && "${ok}" == "true" ]]; then
        run_sok_helm_template_checks "${render_dir}"
        if [[ "${HELM_TEMPLATE_OK}" != "true" ]]; then
            ok=false
        elif [[ "${STRICT}" == "true" && "${HELM_TEMPLATE_CHECKED}" != "true" ]]; then
            ok=false
        fi
    fi

    LIVE_CHECKED=false
    LIVE_OK=true
    local live_output=""
    if [[ "${LIVE}" == "true" && "${ok}" == "true" ]]; then
        LIVE_CHECKED=true
        live_output="$(mktemp)"
        if [[ "${TARGET}" == "pod" ]]; then
            if ! (cd "${render_dir}" && ./preflight.sh && ./wait-ready.sh) >"${live_output}" 2>&1; then
                LIVE_OK=false
                ok=false
            fi
        elif ! (cd "${render_dir}" && SOK_VALIDATE_EXISTING=true ./preflight.sh && ./status.sh) >"${live_output}" 2>&1; then
            LIVE_OK=false
            ok=false
        fi
    fi

    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        printf '{"target":%s,"render_dir":%s,"ok":%s,"missing":%s,"bundle_integrity_ok":%s,"shell_syntax_ok":%s,"python_syntax_ok":%s,"pod_config_ok":%s,"pod_artifacts_checked":%s,"pod_artifacts_ok":%s,"helm_template_checked":%s,"helm_template_ok":%s,"helm_template_skipped":%s,"live_checked":%s,"live_ok":%s}\n' \
            "$(json_string "${TARGET}")" \
            "$(json_string "${render_dir}")" \
            "${ok}" \
            "$(json_array "${missing[@]}")" \
            "${BUNDLE_INTEGRITY_OK}" \
            "${SHELL_SYNTAX_OK}" \
            "${PYTHON_SYNTAX_OK}" \
            "${POD_CONFIG_OK}" \
            "${POD_ARTIFACTS_CHECKED}" \
            "${POD_ARTIFACTS_OK}" \
            "${HELM_TEMPLATE_CHECKED}" \
            "${HELM_TEMPLATE_OK}" \
            "$(json_string "${HELM_TEMPLATE_SKIPPED}")" \
            "${LIVE_CHECKED}" \
            "${LIVE_OK}"
    else
        if [[ "${ok}" == "true" ]]; then
            log "Rendered ${TARGET} assets are present under ${render_dir}."
            if [[ "${TARGET}" == "sok" && "${HELM_TEMPLATE_CHECKED}" == "true" ]]; then
                log "Helm template checks passed for Splunk Operator and Enterprise charts."
            elif [[ "${TARGET}" == "sok" && -n "${HELM_TEMPLATE_SKIPPED}" ]]; then
                log "WARNING: Skipped Helm template checks: ${HELM_TEMPLATE_SKIPPED}."
            fi
        else
            if (( ${#missing[@]} > 0 )); then
                log "ERROR: Missing rendered ${TARGET} assets under ${render_dir}: ${missing[*]}"
            fi
            if [[ "${TARGET}" == "sok" && "${HELM_TEMPLATE_CHECKED}" == "true" && "${HELM_TEMPLATE_OK}" != "true" ]]; then
                log "ERROR: Helm template checks failed for rendered SOK values."
            elif [[ "${TARGET}" == "sok" && "${STRICT}" == "true" && "${HELM_TEMPLATE_CHECKED}" != "true" ]]; then
                log "ERROR: Strict SOK validation requires Helm."
            fi
            if [[ "${SHELL_SYNTAX_OK}" != "true" ]]; then
                log "ERROR: One or more rendered shell helpers are invalid or not executable."
            fi
            if [[ "${PYTHON_SYNTAX_OK}" != "true" ]]; then
                log "ERROR: One or more rendered Python helpers are invalid."
            fi
            if [[ "${BUNDLE_INTEGRITY_OK}" != "true" ]]; then
                log "ERROR: Rendered bundle integrity check failed."
            fi
            if [[ "${TARGET}" == "pod" && "${POD_CONFIG_OK}" != "true" ]]; then
                log "ERROR: POD cluster configuration validation failed."
            fi
            if [[ "${LIVE_CHECKED}" == "true" && "${LIVE_OK}" != "true" ]]; then
                log "ERROR: Live ${TARGET} validation failed."
            fi
        fi
        if [[ "${LIVE_CHECKED}" == "true" && -n "${live_output}" ]]; then
            cat "${live_output}"
        fi
    fi

    [[ -z "${live_output}" ]] || rm -f "${live_output}"

    if [[ "${ok}" != "true" ]]; then
        exit 1
    fi

}

main "$@"
