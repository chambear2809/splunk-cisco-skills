#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-k8s-auto-instrumentation-rendered"
LIVE=false
LIVE_EXPLICIT=false
CHECK_WEBHOOK=false
CHECK_INSTRUMENTATION=false
CHECK_INJECTION=false
CHECK_APM=""
CHECK_BACKUP=false
CHECK_OBI=false
SKIP_APM_CHECK=false
SKIP_BACKUP_CHECK=false
KUBE_CONTEXT=""
ALLOW_CURRENT_CONTEXT=false

usage() {
    cat <<'EOF'
Splunk Observability Kubernetes auto-instrumentation validation

Usage:
  bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR         Rendered output directory
  --live                   Run the complete production gate; requires --check-apm SERVICE
  --check-webhook          Operator MutatingWebhookConfiguration + log scan
  --check-instrumentation  kubectl get otelinst matches rendered CRs
  --check-injection        Assert exact managed annotations + language injection evidence
  --check-obi              Prove rendered OBI ownership/config, rollout, node coverage, logs
  --check-apm SERVICE      Probe api.<realm>.observability.splunkcloud.com/v2/apm/topology
  --check-backup           Every rendered target has a valid rollback snapshot
  --skip-apm-check         With --live only, explicitly omit the APM telemetry gate
  --skip-backup-check      With --live only, explicitly omit rollback-snapshot validation
  --kube-context CTX       Propagate to kubectl invocations
  --allow-current-context  Explicitly acknowledge kubectl's current context
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; LIVE_EXPLICIT=true; shift ;;
        --check-webhook) CHECK_WEBHOOK=true; LIVE=true; shift ;;
        --check-instrumentation) CHECK_INSTRUMENTATION=true; LIVE=true; shift ;;
        --check-injection) CHECK_INJECTION=true; LIVE=true; shift ;;
        --check-obi) CHECK_OBI=true; LIVE=true; shift ;;
        --check-apm) require_arg "$1" "$#" || exit 1; CHECK_APM="$2"; LIVE=true; shift 2 ;;
        --check-backup) CHECK_BACKUP=true; LIVE=true; shift ;;
        --skip-apm-check) SKIP_APM_CHECK=true; shift ;;
        --skip-backup-check) SKIP_BACKUP_CHECK=true; shift ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
        --access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token|--hec-token|--platform-hec-token|--org-token|--api-key)
            reject_secret_arg "$1" "(this validator does not take credentials on argv)"
            exit 1
            ;;
        --access-token=*|--token=*|--bearer-token=*|--api-token=*|--o11y-token=*|--sf-token=*|--hec-token=*|--platform-hec-token=*|--org-token=*|--api-key=*)
            reject_secret_arg "${1%%=*}" "(this validator does not take credentials on argv)"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

# `--live` means the complete production gate. Narrow --check-* invocations
# remain available for diagnostics, while omissions from the complete gate
# require explicit, self-documenting skip flags.
if [[ "${LIVE_EXPLICIT}" == "true" ]]; then
    CHECK_WEBHOOK=true
    CHECK_INSTRUMENTATION=true
    CHECK_INJECTION=true
    if [[ "${SKIP_BACKUP_CHECK}" != "true" ]]; then
        CHECK_BACKUP=true
    fi
    if [[ -z "${CHECK_APM}" && "${SKIP_APM_CHECK}" != "true" ]]; then
        log "ERROR: --live requires --check-apm SERVICE or the explicit --skip-apm-check diagnostic opt-out."
        exit 1
    fi
fi
if [[ "${SKIP_APM_CHECK}" == "true" && -n "${CHECK_APM}" ]]; then
    log "ERROR: --skip-apm-check conflicts with --check-apm."
    exit 1
fi
if [[ "${SKIP_BACKUP_CHECK}" == "true" && "${CHECK_BACKUP}" == "true" ]]; then
    log "ERROR: --skip-backup-check conflicts with --check-backup."
    exit 1
fi
if [[ "${LIVE_EXPLICIT}" != "true" \
    && ( "${SKIP_APM_CHECK}" == "true" || "${SKIP_BACKUP_CHECK}" == "true" ) ]]; then
    log "ERROR: --skip-apm-check and --skip-backup-check are valid only with --live."
    exit 1
fi

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_file() { [[ -f "$1" ]] || { log "ERROR: Missing $1"; exit 1; }; }

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/k8s-instrumentation/instrumentation-cr.yaml"
check_file "${OUTPUT_DIR}/k8s-instrumentation/namespace-annotations.yaml"
check_file "${OUTPUT_DIR}/k8s-instrumentation/workload-annotations.yaml"
check_file "${OUTPUT_DIR}/k8s-instrumentation/annotation-backup-configmap.yaml"
check_file "${OUTPUT_DIR}/k8s-instrumentation/preflight-report.md"
check_file "${OUTPUT_DIR}/k8s-instrumentation/injection-audit.py"
check_file "${OUTPUT_DIR}/k8s-instrumentation/annotation-backup.py"
check_file "${OUTPUT_DIR}/k8s-instrumentation/obi-lifecycle.py"
check_file "${OUTPUT_DIR}/k8s-instrumentation/managed-resource-lifecycle.py"
check_file "${OUTPUT_DIR}/runbook.md"

# Prefer repo-local venv python.
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)"
fi

log "Static: verifying YAML well-formedness and patch-target invariant."
"${PYTHON_BIN}" - "${OUTPUT_DIR}" "${SCRIPT_DIR}/injection_audit.py" \
    "${SCRIPT_DIR}/annotation_backup.py" "${SCRIPT_DIR}/obi_lifecycle.py" \
    "${SCRIPT_DIR}/managed_resource_lifecycle.py" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR: PyYAML missing; install requirements-agent.txt", file=sys.stderr)
    raise SystemExit(1)

root = Path(sys.argv[1])
audit_source = Path(sys.argv[2])
backup_source = Path(sys.argv[3])
obi_source = Path(sys.argv[4])
resource_lifecycle_source = Path(sys.argv[5])
errors = []


def load_all(path):
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    return [doc for doc in docs if doc]


# Every CR must have a name + namespace + a recognized apiVersion.
cr_path = root / "k8s-instrumentation/instrumentation-cr.yaml"
cr_docs = load_all(cr_path)
if not cr_docs:
    errors.append(f"{cr_path}: no Instrumentation documents found.")
seen = set()
language_blocks = {"java", "nodejs", "python", "dotnet", "go", "apacheHttpd", "nginx"}
digest_image = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
for doc in cr_docs:
    if not isinstance(doc, dict):
        errors.append(f"{cr_path}: non-mapping document.")
        continue
    kind = doc.get("kind")
    if kind != "Instrumentation":
        errors.append(f"{cr_path}: expected kind Instrumentation, got {kind!r}.")
    api_version = doc.get("apiVersion", "")
    if not api_version.startswith("opentelemetry.io/"):
        errors.append(f"{cr_path}: unexpected apiVersion {api_version!r}.")
    meta = doc.get("metadata", {})
    key = (meta.get("namespace"), meta.get("name"))
    if key in seen:
        errors.append(f"{cr_path}: duplicate CR {key}.")
    seen.add(key)
    spec = doc.get("spec") or {}
    labels = meta.get("labels") or {}
    if (
        labels.get("app.kubernetes.io/name") != "splunk-otel-auto-instrumentation"
        or labels.get("app.kubernetes.io/managed-by")
        != "splunk-observability-k8s-auto-instrumentation-setup"
    ):
        errors.append(f"{cr_path}: {key} is missing the exact ownership labels.")
    for language in sorted(language_blocks & set(spec)):
        block = spec.get(language) or {}
        image = block.get("image") if isinstance(block, dict) else None
        if not isinstance(image, str) or not digest_image.fullmatch(image):
            errors.append(
                f"{cr_path}: {key} {language} image is not pinned by an immutable @sha256 digest."
            )

obi_path = root / "k8s-instrumentation/obi-daemonset.yaml"
if obi_path.exists():
    for document in load_all(obi_path):
        containers = (
            document.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or []
        )
        for container in containers:
            image = container.get("image") if isinstance(container, dict) else None
            if not isinstance(image, str) or not digest_image.fullmatch(image):
                errors.append(f"{obi_path}: OBI image is not pinned by an immutable @sha256 digest.")

rendered_audit = root / "k8s-instrumentation/injection-audit.py"
try:
    if rendered_audit.read_bytes() != audit_source.read_bytes():
        errors.append(
            f"{rendered_audit}: rendered injection auditor differs from the reviewed skill source."
        )
except OSError as exc:
    errors.append(f"{rendered_audit}: could not compare reviewed injection auditor ({exc}).")
for rendered_helper, reviewed_source, label in (
    (root / "k8s-instrumentation/annotation-backup.py", backup_source, "annotation backup helper"),
    (root / "k8s-instrumentation/obi-lifecycle.py", obi_source, "OBI lifecycle helper"),
    (
        root / "k8s-instrumentation/managed-resource-lifecycle.py",
        resource_lifecycle_source,
        "managed-resource lifecycle helper",
    ),
):
    try:
        if rendered_helper.read_bytes() != reviewed_source.read_bytes():
            errors.append(f"{rendered_helper}: rendered {label} differs from the reviewed skill source.")
    except OSError as exc:
        errors.append(f"{rendered_helper}: could not compare reviewed {label} ({exc}).")

# Workload annotations must target spec.template.metadata.annotations, not
# top-level metadata.annotations. This is the single most common authoring
# bug in operator-driven auto-instrumentation; the static check enforces it.
wl_path = root / "k8s-instrumentation/workload-annotations.yaml"
workload_docs = []
for doc in load_all(wl_path):
    if not isinstance(doc, dict):
        continue
    if doc.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
        continue
    workload_docs.append(doc)
    annotations = doc.get("metadata", {}).get("annotations") or {}
    template_annotations = (
        doc.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations") or {}
    )
    if any(k.startswith("instrumentation.opentelemetry.io/") for k in annotations):
        errors.append(
            f"{wl_path}: {doc.get('metadata', {}).get('name')} places inject-<lang> at "
            "metadata.annotations instead of spec.template.metadata.annotations."
        )
    go_bound = any(k.endswith("/inject-go") for k in template_annotations)
    if go_bound and "instrumentation.opentelemetry.io/otel-go-auto-target-exe" not in template_annotations:
        errors.append(
            f"{wl_path}: Go-bound workload missing otel-go-auto-target-exe annotation."
        )

# Backup ConfigMap has the expected shape.
backup_path = root / "k8s-instrumentation/annotation-backup-configmap.yaml"
for doc in load_all(backup_path):
    if not isinstance(doc, dict):
        continue
    if doc.get("kind") != "ConfigMap":
        errors.append(f"{backup_path}: expected kind ConfigMap, got {doc.get('kind')!r}.")

# Reject any .NET Framework references in rendered manifests. Reference docs
# discuss .NET Framework only in the context of explicit refusal, so we limit
# the strict check to manifests (.yaml/.yml/.json) where any mention is a bug.
for p in root.rglob("*"):
    if not p.is_file():
        continue
    if p.suffix not in {".yaml", ".yml", ".json"}:
        continue
    body = p.read_text(encoding="utf-8")
    if ".NET Framework" in body or "dotnet framework" in body.lower():
        errors.append(f"{p}: manifest references .NET Framework (unsupported).")

# Scrub: no credential assignments or credential-bearing headers in any
# rendered file, not only shell scripts.
token_re = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|api[_-]?token|authorization|bearer(?:[_-]?token)?|"
    r"hec[_-]?token|org[_-]?token|password|passwd|secret|sf[_-]?token|x-sf-token)"
    r"\s*[:=]\s*[^\s,;}]{4,}"
)
env_secret_re = re.compile(
    r'''(?is)(?:"name"\s*:\s*"|name\s*:\s*)
    (?:[^\n"]*(?:api[_-]?key|authorization|bearer|hec|password|secret|token)[^\n"]*)
    (?:"?\s*,?\s*(?:"value"\s*:\s*"|value\s*:\s*))(?!["']?\s*$)''',
    re.VERBOSE,
)
bearer_value_re = re.compile(r'''(?i)(?:"value"\s*:\s*"|value\s*:\s*)\s*(?:Bearer|X-SF-Token)\b''')
secret_key_re = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|api[_-]?token|authorization|bearer|credential|"
    r"hec(?:[_-]?token)?|org[_-]?token|password|passwd|secret|sf[_-]?token|token)"
)
safe_secret_reference_keys = {"image_pull_secret", "imagePullSecret", "imagePullSecrets"}


def scan_structured_secrets(value, path):
    if isinstance(value, dict):
        env_name = value.get("name")
        if (
            isinstance(env_name, str)
            and secret_key_re.search(env_name)
            and value.get("value") not in (None, "")
        ):
            errors.append(f"{path}: environment entry {env_name!r} contains credential material.")
        for key, child in value.items():
            key_text = str(key)
            if (
                key_text not in safe_secret_reference_keys
                and secret_key_re.search(key_text)
                and child not in (None, "", [], {})
            ):
                errors.append(f"{path}.{key_text}: secret-like key has a rendered value.")
            scan_structured_secrets(child, f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_structured_secrets(child, f"{path}[{index}]")


for p in root.rglob("*"):
    if not p.is_file():
        continue
    body = p.read_text(encoding="utf-8", errors="replace")
    if token_re.search(body) or env_secret_re.search(body) or bearer_value_re.search(body):
        errors.append(f"{p}: rendered file appears to embed credential material.")
    if p.suffix in {".yaml", ".yml", ".json"}:
        try:
            structured_docs = (
                [json.loads(body)]
                if p.suffix == ".json"
                else [doc for doc in yaml.safe_load_all(body) if doc is not None]
            )
        except (json.JSONDecodeError, yaml.YAMLError):
            # Dedicated syntax checks report the primary parsing error.
            structured_docs = []
        for index, document in enumerate(structured_docs):
            scan_structured_secrets(document, f"{p} document[{index}]")

# metadata.json must parse and have the expected top-level keys.
meta_path = root / "metadata.json"
try:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    errors.append(f"{meta_path}: invalid JSON ({exc}).")
    meta = {}
for key in (
    "skill",
    "spec_digest",
    "preflight",
    "rendered_files",
    "targets",
    "namespace_targets",
    "operator_resources",
    "instrumentation_documents",
    "obi_contract",
    "apm_services",
):
    if key not in meta:
        errors.append(f"{meta_path}: missing required key '{key}'.")
if meta.get("skill") != "splunk-observability-k8s-auto-instrumentation-setup":
    errors.append(f"{meta_path}: unexpected skill identity {meta.get('skill')!r}.")
if meta.get("instrumentation_documents") != cr_docs:
    errors.append(
        f"{meta_path}: instrumentation_documents do not exactly match instrumentation-cr.yaml."
    )
obi_contract = meta.get("obi_contract")
if not isinstance(obi_contract, dict) or not isinstance(obi_contract.get("documents"), list) or not isinstance(obi_contract.get("scc_documents"), list):
    errors.append(f"{meta_path}: obi_contract is malformed.")
else:
    obi_docs = load_all(obi_path) if obi_path.exists() else []
    scc_path = root / "k8s-instrumentation/openshift-scc-obi.yaml"
    scc_docs = load_all(scc_path) if scc_path.exists() else []
    if obi_docs != obi_contract["documents"] or scc_docs != obi_contract["scc_documents"]:
        errors.append(f"{meta_path}: OBI document contract does not exactly match rendered manifests.")
    if bool(obi_contract.get("enabled")) != bool(obi_docs):
        errors.append(f"{meta_path}: OBI enabled state does not match rendered manifests.")
namespace_path = root / "k8s-instrumentation/namespace-annotations.yaml"
actual_namespaces = {}
for document in load_all(namespace_path):
    metadata = document.get("metadata") or {}
    namespace = str(metadata.get("name") or "")
    if document.get("kind") != "Namespace" or not namespace or namespace in actual_namespaces:
        errors.append(f"{namespace_path}: missing, duplicate, or invalid Namespace identity.")
        continue
    actual_namespaces[namespace] = metadata.get("annotations") or {}
expected_namespaces = {}
namespace_targets = meta.get("namespace_targets")
if not isinstance(namespace_targets, list):
    errors.append(f"{meta_path}: namespace_targets must be a list.")
else:
    for row in namespace_targets:
        if not isinstance(row, dict):
            errors.append(f"{meta_path}: namespace_targets contains a non-object row.")
            continue
        namespace = str(row.get("namespace") or "")
        target = str(row.get("target") or "")
        annotations = row.get("annotations")
        if (
            not namespace
            or target != f"Namespace/{namespace}"
            or not isinstance(annotations, dict)
            or namespace in expected_namespaces
        ):
            errors.append(f"{meta_path}: namespace_targets contains an invalid or duplicate row.")
            continue
        expected_namespaces[namespace] = annotations
if actual_namespaces != expected_namespaces:
    errors.append(
        f"{meta_path}: namespace_targets do not exactly match namespace-annotations.yaml."
    )

# Workload metadata is the live audit's allow-list. Derive its grouped contract
# from workload-annotations.yaml so deleting or altering a metadata row cannot
# silently omit a rendered workload/language from the complete live gate.
metadata_targets = meta.get("targets")
if not isinstance(metadata_targets, list) or any(
    not isinstance(row, dict) for row in metadata_targets
):
    errors.append(f"{meta_path}: targets must be a list of objects.")
else:
    metadata_groups = {}
    seen_rows = set()
    for row in metadata_targets:
        kind = str(row.get("kind") or "")
        namespace = str(row.get("namespace") or "")
        name = str(row.get("name") or "")
        language = str(row.get("language") or "")
        target = f"{kind}/{namespace}/{name}"
        annotations = row.get("annotations")
        inject_key = f"instrumentation.opentelemetry.io/inject-{language}"
        expected_key = f"snapshot-{hashlib.sha256(target.encode('utf-8')).hexdigest()[:20]}"
        identity = (kind, namespace, name)
        row_identity = (*identity, language)
        if (
            not all(row_identity)
            or row.get("target") != target
            or row.get("key") != expected_key
            or row_identity in seen_rows
            or not isinstance(annotations, dict)
            or inject_key not in annotations
            or any(
                not str(key).startswith("instrumentation.opentelemetry.io/")
                for key in annotations
            )
            or any(
                str(key).startswith("instrumentation.opentelemetry.io/inject-")
                and key != inject_key
                for key in annotations
            )
            or row.get("cr")
            != ("" if annotations.get(inject_key) == "false" else annotations.get(inject_key))
        ):
            errors.append(f"{meta_path}: targets contains an invalid or duplicate row.")
            continue
        seen_rows.add(row_identity)
        group = metadata_groups.setdefault(identity, {})
        for key, value in annotations.items():
            if key in group and group[key] != value:
                errors.append(f"{meta_path}: targets contains conflicting annotations for {target}.")
            group[key] = value

    manifest_groups = {}
    for document in workload_docs:
        document_meta = document.get("metadata") or {}
        identity = (
            str(document.get("kind") or ""),
            str(document_meta.get("namespace") or ""),
            str(document_meta.get("name") or ""),
        )
        annotations = (
            (((document.get("spec") or {}).get("template") or {}).get("metadata") or {})
            .get("annotations")
        )
        if not all(identity) or identity in manifest_groups or not isinstance(annotations, dict):
            errors.append(f"{wl_path}: missing, duplicate, or invalid workload identity.")
            continue
        manifest_groups[identity] = annotations
    if metadata_groups != manifest_groups:
        errors.append(f"{meta_path}: targets do not exactly match workload-annotations.yaml.")
preflight = meta.get("preflight")
if not isinstance(preflight, dict):
    errors.append(f"{meta_path}: preflight must be an object.")
    preflight_errors = []
else:
    preflight_errors = preflight.get("errors", [])
if not isinstance(preflight_errors, list):
    errors.append(f"{meta_path}: preflight.errors must be a list.")
elif preflight_errors:
    errors.append(f"{meta_path}: rendered packet has unresolved preflight errors.")
top_level_errors = meta.get("errors", [])
if not isinstance(top_level_errors, list):
    errors.append(f"{meta_path}: errors must be a list.")
elif top_level_errors:
    errors.append(f"{meta_path}: rendered packet has unresolved top-level errors.")

if errors:
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    raise SystemExit(1)
print("Static validation: OK")
PY

if [[ "${LIVE}" != "true" ]]; then
    log "Static validation passed. Pass --live or a --check-* flag for cluster probes."
    exit 0
fi

OBI_ENABLED="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json, sys
metadata = json.load(open(sys.argv[1], encoding="utf-8"))
print("true" if metadata.get("obi_enabled") is True else "false")
PY
)"
if [[ "${LIVE_EXPLICIT}" == "true" && "${OBI_ENABLED}" == "true" ]]; then
    CHECK_OBI=true
fi
if [[ "${CHECK_OBI}" == "true" && "${OBI_ENABLED}" != "true" ]]; then
    log "ERROR: --check-obi was requested, but metadata.json does not enable OBI."
    exit 1
fi

if [[ -n "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" == "true" ]]; then
    log "ERROR: --kube-context conflicts with --allow-current-context."
    exit 1
fi
if [[ -z "${KUBE_CONTEXT}" && "${ALLOW_CURRENT_CONTEXT}" != "true" ]]; then
    log "ERROR: live validation requires --kube-context CTX or the explicit --allow-current-context acknowledgement."
    exit 1
fi

KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi

if [[ "${CHECK_WEBHOOK}" == "true" \
    || "${CHECK_INSTRUMENTATION}" == "true" \
    || "${CHECK_INJECTION}" == "true" \
    || "${CHECK_BACKUP}" == "true" \
    || "${CHECK_OBI}" == "true" ]]; then
    command -v kubectl >/dev/null 2>&1 || {
        log "ERROR: kubectl is required for the requested live cluster checks."
        exit 1
    }
fi

# Serialize the kubectl argv as JSON in an env var. The previous
# `kube = ${KUBECTL[@]@Q}` heredoc trick produced concatenated string literals
# in the embedded Python (`'kubectl' '--context' 'foo'` -> 'kubectl--contextfoo'),
# which made list(kube) iterate characters and never invoke kubectl correctly.
KUBE_JSON="$("${PYTHON_BIN}" -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${KUBECTL[@]}")"
export KUBE_JSON

if [[ "${CHECK_WEBHOOK}" == "true" ]]; then
    log "Live: --check-webhook"
    operator_facts="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/metadata.json" <<'PY'
import hashlib
import json
import re
import sys

metadata = json.load(open(sys.argv[1], encoding="utf-8"))
base = metadata.get("base") or {}
release = str(base.get("release") or "")
namespace = str(base.get("namespace") or "")
dns_label = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
if not dns_label.fullmatch(release) or not dns_label.fullmatch(namespace):
    raise SystemExit("metadata.json contains an invalid base release or namespace")
raw = release if "operator" in release else f"{release}-operator"
if len(raw) <= 31:
    operator_name = raw.rstrip("-")
else:
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    operator_name = f"{raw[:22].rstrip('-')}-{digest}"
expected = {
    "namespace": namespace,
    "deployment_name": operator_name,
    "webhook_configuration_name": f"{operator_name}-mutation",
    "webhook_service_name": f"{operator_name}-webhook",
}
if metadata.get("operator_resources") != expected:
    raise SystemExit("metadata.json operator_resources do not match the bounded base-collector names")
print("\t".join(expected[key] for key in (
    "namespace",
    "webhook_configuration_name",
    "webhook_service_name",
)))
PY
    )" || {
        log "ERROR: Could not derive exact Operator resource names from metadata.json."
        exit 1
    }
    IFS=$'\t' read -r operator_namespace expected_webhook expected_webhook_service <<<"${operator_facts}"
    webhook_state_dir="$(mktemp -d)"
    chmod 700 "${webhook_state_dir}"
    trap 'rm -rf "${webhook_state_dir}"' EXIT
    if ! "${KUBECTL[@]}" get mutatingwebhookconfiguration "${expected_webhook}" -o json \
        >"${webhook_state_dir}/webhook.json"; then
        log "ERROR: Kubernetes API failed while reading MutatingWebhookConfiguration ${expected_webhook}."
        exit 1
    fi
    if ! "${KUBECTL[@]}" -n "${operator_namespace}" get service \
        "${expected_webhook_service}" -o json >"${webhook_state_dir}/service.json"; then
        log "ERROR: Kubernetes API failed while reading webhook Service ${operator_namespace}/${expected_webhook_service}."
        exit 1
    fi
    route_kind="endpointslice"
    route_file="${webhook_state_dir}/endpointslices.json"
    if "${KUBECTL[@]}" -n "${operator_namespace}" get endpointslice \
        -l "kubernetes.io/service-name=${expected_webhook_service}" -o json \
        >"${route_file}" 2>"${webhook_state_dir}/endpointslice.stderr"; then
        if ! endpoint_slice_count="$("${PYTHON_BIN}" - "${route_file}" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"EndpointSlice response was not valid JSON: {exc}")
if payload.get("kind") not in {"EndpointSliceList", "List"} or not isinstance(payload.get("items"), list):
    raise SystemExit("EndpointSlice response was not a Kubernetes list")
print(len(payload["items"]))
PY
        )"; then
            log "ERROR: Kubernetes returned an invalid EndpointSlice response for ${operator_namespace}/${expected_webhook_service}."
            exit 1
        fi
    else
        endpoint_slice_count=0
    fi
    # Legacy clusters and narrowly-scoped RBAC may not expose EndpointSlice.
    # Fall back only when the API query failed or returned no matching slices;
    # a present but unready slice is validated and fails closed below.
    if [[ "${endpoint_slice_count}" == "0" ]]; then
        route_kind="endpoints"
        route_file="${webhook_state_dir}/endpoints.json"
        if ! "${KUBECTL[@]}" -n "${operator_namespace}" get endpoints \
            "${expected_webhook_service}" -o json >"${route_file}"; then
            log "ERROR: Kubernetes API failed while reading webhook EndpointSlices and fallback Endpoints ${operator_namespace}/${expected_webhook_service}."
            exit 1
        fi
    fi
    if ! webhook_policy="$("${PYTHON_BIN}" - \
        "${webhook_state_dir}/webhook.json" \
        "${webhook_state_dir}/service.json" \
        "${route_file}" "${route_kind}" \
        "${expected_webhook}" "${expected_webhook_service}" "${operator_namespace}" <<'PY'
import base64
import binascii
import json
import re
import sys

webhook_path, service_path, route_path, route_kind, expected, service_name, namespace = sys.argv[1:]
webhook_obj = json.load(open(webhook_path, encoding="utf-8"))
service_obj = json.load(open(service_path, encoding="utf-8"))
route_obj = json.load(open(route_path, encoding="utf-8"))

if webhook_obj.get("kind") != "MutatingWebhookConfiguration":
    raise SystemExit("ERROR: Kubernetes returned the wrong webhook resource kind")
if str((webhook_obj.get("metadata") or {}).get("name") or "") != expected:
    raise SystemExit("ERROR: Kubernetes returned a different webhook resource")
pod_hooks = [row for row in (webhook_obj.get("webhooks") or []) if row.get("name") == "mpod.kb.io"]
if len(pod_hooks) != 1:
    raise SystemExit("ERROR: MutatingWebhookConfiguration does not contain exactly one mpod.kb.io hook")
hook = pod_hooks[0]
if "v1" not in (hook.get("admissionReviewVersions") or []):
    raise SystemExit("ERROR: pod webhook does not support admissionReviewVersions v1")
if hook.get("sideEffects") not in {"None", "NoneOnDryRun"}:
    raise SystemExit("ERROR: pod webhook has unsafe or missing sideEffects")
failure_policy = str(hook.get("failurePolicy") or "")
if failure_policy != "Ignore":
    raise SystemExit("ERROR: pod webhook failurePolicy differs from the pinned chart contract (Ignore)")
timeout = hook.get("timeoutSeconds")
if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 30:
    raise SystemExit("ERROR: pod webhook timeoutSeconds is outside the Kubernetes bound")
if hook.get("namespaceSelector") not in (None, {}) or hook.get("objectSelector") not in (None, {}):
    raise SystemExit("ERROR: pod webhook selectors do not prove admission for every rendered target")

client = hook.get("clientConfig") or {}
service = client.get("service") or {}
if service != {
    "name": service_name,
    "namespace": namespace,
    "path": "/mutate-v1-pod",
    "port": 443,
}:
    raise SystemExit("ERROR: pod webhook clientConfig.service does not match the Operator webhook Service")
ca_bundle = client.get("caBundle")
if not isinstance(ca_bundle, str) or not ca_bundle:
    raise SystemExit("ERROR: pod webhook has no injected CA bundle")
try:
    decoded_ca = base64.b64decode(ca_bundle, validate=True)
except (ValueError, binascii.Error) as exc:
    raise SystemExit("ERROR: pod webhook CA bundle is not valid base64") from exc
try:
    pem_text = decoded_ca.decode("ascii")
except UnicodeDecodeError as exc:
    raise SystemExit("ERROR: pod webhook CA bundle is not ASCII PEM") from exc
pem_blocks = re.findall(
    r"-----BEGIN CERTIFICATE-----\s*([A-Za-z0-9+/=\s]+?)\s*-----END CERTIFICATE-----",
    pem_text,
)
if not pem_blocks:
    raise SystemExit("ERROR: pod webhook CA bundle contains no complete PEM certificate block")
for encoded_certificate in pem_blocks:
    compact = re.sub(r"\s+", "", encoded_certificate)
    try:
        certificate_bytes = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SystemExit("ERROR: pod webhook CA bundle contains malformed PEM certificate data") from exc
    if not certificate_bytes:
        raise SystemExit("ERROR: pod webhook CA bundle contains an empty PEM certificate")

matching_rule = False
for rule in hook.get("rules") or []:
    if (
        "" in (rule.get("apiGroups") or [])
        and "v1" in (rule.get("apiVersions") or [])
        and "CREATE" in (rule.get("operations") or [])
        and "pods" in (rule.get("resources") or [])
        and rule.get("scope") == "Namespaced"
    ):
        matching_rule = True
        break
if not matching_rule:
    raise SystemExit("ERROR: pod webhook has no namespaced core/v1 CREATE pods admission rule")

service_meta = service_obj.get("metadata") or {}
service_spec = service_obj.get("spec") or {}
if (
    service_obj.get("kind") != "Service"
    or service_meta.get("name") != service_name
    or service_meta.get("namespace") != namespace
    or service_spec.get("type", "ClusterIP") != "ClusterIP"
    or service_spec.get("clusterIP") in (None, "", "None")
    or not isinstance(service_spec.get("selector"), dict)
    or not service_spec["selector"]
):
    raise SystemExit("ERROR: Operator webhook Service is absent, headless, or has no selector")
ports = service_spec.get("ports") or []
webhook_service_ports = [
    row
    for row in ports
    if (
        row.get("name") in (None, "")
        and row.get("port") == 443
        and row.get("protocol", "TCP") == "TCP"
        and row.get("targetPort") == "webhook-server"
    )
]
if len(webhook_service_ports) != 1:
    raise SystemExit("ERROR: Operator webhook Service does not expose the exact webhook-server port contract")

if route_kind == "endpointslice":
    if route_obj.get("kind") not in {"EndpointSliceList", "List"}:
        raise SystemExit("ERROR: Kubernetes returned the wrong EndpointSlice list kind")
    slices = route_obj.get("items")
    if not isinstance(slices, list) or not slices:
        raise SystemExit("ERROR: Kubernetes returned no matching webhook EndpointSlices")
    route_ready = False
    for endpoint_slice in slices:
        metadata = endpoint_slice.get("metadata") or {}
        labels = metadata.get("labels") or {}
        if (
            endpoint_slice.get("apiVersion") != "discovery.k8s.io/v1"
            or endpoint_slice.get("kind") != "EndpointSlice"
            or metadata.get("namespace") != namespace
            or labels.get("kubernetes.io/service-name") != service_name
        ):
            raise SystemExit("ERROR: Kubernetes returned an EndpointSlice outside the webhook Service identity")
        ready_addresses = any(
            endpoint.get("conditions", {}).get("ready") is True
            and endpoint.get("conditions", {}).get("terminating") is not True
            and bool(endpoint.get("addresses"))
            for endpoint in (endpoint_slice.get("endpoints") or [])
        )
        pinned_port = any(
            port.get("name") in (None, "", "webhook-server")
            and port.get("protocol", "TCP") == "TCP"
            and port.get("port") == 9443
            for port in (endpoint_slice.get("ports") or [])
        )
        route_ready = route_ready or (ready_addresses and pinned_port)
elif route_kind == "endpoints":
    endpoints_meta = route_obj.get("metadata") or {}
    if (
        route_obj.get("kind") != "Endpoints"
        or endpoints_meta.get("name") != service_name
        or endpoints_meta.get("namespace") != namespace
    ):
        raise SystemExit("ERROR: Kubernetes returned different webhook Endpoints")
    route_ready = any(
        bool(subset.get("addresses"))
        and any(
            port.get("name") in (None, "", "webhook-server")
            and port.get("protocol", "TCP") == "TCP"
            and port.get("port") == 9443
            for port in (subset.get("ports") or [])
        )
        for subset in (route_obj.get("subsets") or [])
    )
else:
    raise SystemExit("ERROR: unknown webhook route evidence kind")
if not route_ready:
    raise SystemExit(
        "ERROR: Operator webhook Service has no ready address on the pinned 9443/TCP endpoint port"
    )
print(f"{failure_policy}\t{route_kind}")
PY
    )"; then
        log "ERROR: Operator pod admission webhook is not route-ready."
        exit 1
    fi
    IFS=$'\t' read -r webhook_policy_value webhook_route_source <<<"${webhook_policy}"
    log "  MutatingWebhookConfiguration ${expected_webhook}: pod admission route ready (failurePolicy=${webhook_policy_value}); source=${webhook_route_source}."
    if ! operator_pods="$("${KUBECTL[@]}" -n "${operator_namespace}" get pods \
        -l app.kubernetes.io/name=operator -o json)"; then
        log "ERROR: Kubernetes API failed while reading OpenTelemetry Operator pods in ${operator_namespace}."
        exit 1
    fi
    "${PYTHON_BIN}" - "${operator_namespace}" 3<<<"${operator_pods}" <<'PY'
import json
import os
import sys

namespace = sys.argv[1]
try:
    with os.fdopen(3, encoding="utf-8") as handle:
        data = json.load(handle)
except json.JSONDecodeError as exc:
    print(f"ERROR: invalid Operator pod JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)

pods = data.get("items") or []
if not pods:
    print(
        f"ERROR: no OpenTelemetry Operator pods found in {namespace} with "
        "app.kubernetes.io/name=operator.",
        file=sys.stderr,
    )
    raise SystemExit(1)
for pod in pods:
    name = str((pod.get("metadata") or {}).get("name") or "<unknown>")
    phase = str((pod.get("status") or {}).get("phase") or "")
    ready = any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in ((pod.get("status") or {}).get("conditions") or [])
    )
    if phase != "Running" or not ready:
        print(f"ERROR: Operator pod {namespace}/{name} is not Running and Ready.", file=sys.stderr)
        raise SystemExit(1)
PY
    operator_log="$(mktemp)"
    trap 'rm -f "${operator_log}"; rm -rf "${webhook_state_dir}"' EXIT
    if ! "${KUBECTL[@]}" -n "${operator_namespace}" logs \
        -l app.kubernetes.io/name=operator --all-containers=true --tail=200 >"${operator_log}" 2>&1; then
        log "ERROR: Failed to retrieve OpenTelemetry Operator logs from ${operator_namespace}."
        exit 1
    fi
    if grep -Eiq 'failed to call webhook|webhook[^[:cntrl:]]*(error|failed)|(^|[^a-z])(panic|fatal)([^a-z]|$)' "${operator_log}"; then
        log "ERROR: OpenTelemetry Operator logs contain webhook, panic, or fatal errors."
        exit 1
    fi
    rm -f "${operator_log}"
    rm -rf "${webhook_state_dir}"
    trap - EXIT
    log "  Operator pods are Ready and recent logs contain no webhook failure pattern."
fi

if [[ "${CHECK_INSTRUMENTATION}" == "true" ]]; then
    log "Live: --check-instrumentation"
    "${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR: PyYAML is required to compare rendered and live Instrumentation CRs.", file=sys.stderr)
    raise SystemExit(1)

root = Path(sys.argv[1])
meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
kube = json.loads(os.environ["KUBE_JSON"])
crs = meta.get("instrumentation_crs") or []
if not crs:
    print("ERROR: metadata.json contains no Instrumentation CRs to validate.", file=sys.stderr)
    sys.exit(1)

rendered_path = root / "k8s-instrumentation/instrumentation-cr.yaml"
rendered_docs = [
    document
    for document in yaml.safe_load_all(rendered_path.read_text(encoding="utf-8"))
    if document is not None
]
rendered_by_identity = {}
for document in rendered_docs:
    if not isinstance(document, dict):
        print(f"ERROR: {rendered_path} contains a non-object document.", file=sys.stderr)
        raise SystemExit(1)
    metadata = document.get("metadata") or {}
    identity = (str(metadata.get("namespace") or ""), str(metadata.get("name") or ""))
    if not all(identity) or identity in rendered_by_identity:
        print(f"ERROR: {rendered_path} contains a missing or duplicate CR identity.", file=sys.stderr)
        raise SystemExit(1)
    rendered_by_identity[identity] = document

metadata_identities = {
    (str(cr.get("namespace") or ""), str(cr.get("name") or ""))
    for cr in crs
    if isinstance(cr, dict)
}
if metadata_identities != set(rendered_by_identity):
    print(
        "ERROR: metadata.json Instrumentation CR identities do not exactly match instrumentation-cr.yaml.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def managed_projection(document):
    metadata = document.get("metadata") or {}
    labels = metadata.get("labels") or {}
    return {
        "apiVersion": document.get("apiVersion"),
        "kind": document.get("kind"),
        "metadata": {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
            "labels": {
                "app.kubernetes.io/name": labels.get("app.kubernetes.io/name"),
                "app.kubernetes.io/managed-by": labels.get(
                    "app.kubernetes.io/managed-by"
                ),
            },
        },
        "spec": document.get("spec"),
    }


for (ns, name), rendered in sorted(rendered_by_identity.items()):
    proc = subprocess.run(kube + ["-n", ns, "get", "otelinst", name, "-o", "json"], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"ERROR: otelinst {ns}/{name} not found:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)
    try:
        live = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: otelinst {ns}/{name} returned invalid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if managed_projection(live) != managed_projection(rendered):
        print(
            f"ERROR: otelinst {ns}/{name} managed spec drifted from instrumentation-cr.yaml.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"  otelinst {ns}/{name}: managed spec matches rendered CR")
PY
fi

if [[ "${CHECK_INJECTION}" == "true" ]]; then
    log "Live: --check-injection"
    audit_args=(--output-dir "${OUTPUT_DIR}" --target-all)
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        audit_args+=(--kube-context "${KUBE_CONTEXT}")
    else
        audit_args+=(--allow-current-context)
    fi
    if ! "${PYTHON_BIN}" "${OUTPUT_DIR}/k8s-instrumentation/injection-audit.py" "${audit_args[@]}"; then
        log "ERROR: Deep auto-instrumentation injection audit failed."
        exit 1
    fi
fi

if [[ "${CHECK_OBI}" == "true" ]]; then
    log "Live: --check-obi"
    obi_args=(--mode validate --metadata "${OUTPUT_DIR}/metadata.json")
    if [[ -n "${KUBE_CONTEXT}" ]]; then obi_args+=(--kube-context "${KUBE_CONTEXT}"); fi
    if ! "${PYTHON_BIN}" "${OUTPUT_DIR}/k8s-instrumentation/obi-lifecycle.py" "${obi_args[@]}"; then
        log "ERROR: OBI lifecycle validation failed."
        exit 1
    fi
fi

if [[ -n "${CHECK_APM}" ]]; then
    log "Live: --check-apm ${CHECK_APM}"
    if [[ -z "${SPLUNK_O11Y_REALM:-}" || -z "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
        log "ERROR: SPLUNK_O11Y_REALM and SPLUNK_O11Y_TOKEN_FILE are required for --check-apm."
        exit 1
    fi
    if ! APM_REALM="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/metadata.json" "${CHECK_APM}" "${SPLUNK_O11Y_REALM}" <<'PY'
import json, sys
metadata_path, requested_service, environment_realm = sys.argv[1:]
metadata = json.load(open(metadata_path, encoding="utf-8"))
realm = str(metadata.get("realm") or "")
if not realm or environment_realm != realm:
    raise SystemExit("ERROR: SPLUNK_O11Y_REALM does not exactly match the realm bound in metadata.json")
services = metadata.get("apm_services")
if not isinstance(services, list) or any(not isinstance(row, dict) for row in services):
    raise SystemExit("ERROR: metadata.json apm_services contract is malformed")
matches = [
    row for row in services
    if row.get("service") == requested_service and row.get("realm") == realm
]
if not matches:
    raise SystemExit(
        "ERROR: --check-apm service is not allowlisted by a rendered workload target in metadata.json"
    )
expected_cluster = str(metadata.get("cluster_name") or "")
expected_environment = str(metadata.get("deployment_environment") or "")
if any(
    row.get("cluster_name") != expected_cluster
    or row.get("deployment_environment") != expected_environment
    or not row.get("target")
    for row in matches
):
    raise SystemExit("ERROR: metadata.json APM service binding is inconsistent")
print(realm)
PY
    )"; then
        log "ERROR: APM realm/service contract validation failed."
        exit 1
    fi
    case "${SPLUNK_O11Y_REALM}" in
        us0|us1|us2|us3|us2-gcp|au0|eu0|eu1|eu2|jp0|sg0) ;;
        *)
            log "ERROR: SPLUNK_O11Y_REALM is not a supported Splunk Observability realm."
            exit 1
            ;;
    esac
    command -v curl >/dev/null 2>&1 || {
        log "ERROR: curl is required for --check-apm."
        exit 1
    }
    header_file="$(mktemp)"
    chmod 600 "${header_file}"
    trap 'rm -f "${header_file}"' EXIT
    "${PYTHON_BIN}" - "${SPLUNK_O11Y_TOKEN_FILE}" "${header_file}" <<'PY'
import os
import stat
import sys

path, header_path = sys.argv[1:]
if not hasattr(os, "O_NOFOLLOW"):
    print("ERROR: secure token validation requires O_NOFOLLOW support.", file=sys.stderr)
    raise SystemExit(1)
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    print(f"ERROR: cannot safely open SPLUNK_O11Y_TOKEN_FILE: {exc}", file=sys.stderr)
    raise SystemExit(1)
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        print("ERROR: SPLUNK_O11Y_TOKEN_FILE must be a single-link, non-symlink regular file.", file=sys.stderr)
        raise SystemExit(1)
    if stat.S_IMODE(before.st_mode) != 0o600:
        print("ERROR: SPLUNK_O11Y_TOKEN_FILE must have mode 0600.", file=sys.stderr)
        raise SystemExit(1)
    if before.st_size < 1 or before.st_size > 16 * 1024:
        print("ERROR: SPLUNK_O11Y_TOKEN_FILE size is outside the 1-byte through 16-KiB bound.", file=sys.stderr)
        raise SystemExit(1)
    chunks = []
    remaining = 16 * 1024 + 1
    while remaining:
        chunk = os.read(descriptor, min(4096, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(descriptor)
    path_after = os.stat(path, follow_symlinks=False)
finally:
    os.close(descriptor)
fingerprint = lambda info: (
    info.st_dev,
    info.st_ino,
    info.st_size,
    info.st_mtime_ns,
    info.st_ctime_ns,
    info.st_nlink,
    stat.S_IMODE(info.st_mode),
)
try:
    if fingerprint(before) != fingerprint(after):
        raise ValueError("changed while it was being read")
    if (path_after.st_dev, path_after.st_ino) != (after.st_dev, after.st_ino):
        raise ValueError("path identity changed while it was being read")
    data = b"".join(chunks)
    if data.endswith(b"\r\n"):
        data = data[:-2]
    elif data.endswith(b"\n"):
        data = data[:-1]
    if (
        not data
        or b"\x00" in data
        or b"\r" in data
        or b"\n" in data
        or data != data.strip()
        or any(byte <= 0x20 or byte == 0x7F for byte in data)
        or any(byte > 0x7E for byte in data)
    ):
        raise ValueError("must contain one nonempty printable-ASCII token without whitespace or control bytes")
except ValueError as exc:
    print(f"ERROR: SPLUNK_O11Y_TOKEN_FILE {exc}.", file=sys.stderr)
    raise SystemExit(1)

header_before = os.lstat(header_path)
if (
    not stat.S_ISREG(header_before.st_mode)
    or header_before.st_nlink != 1
    or stat.S_IMODE(header_before.st_mode) != 0o600
):
    raise SystemExit("ERROR: private token-header file failed validation")
header_fd = os.open(header_path, os.O_WRONLY | os.O_NOFOLLOW)
try:
    header_opened = os.fstat(header_fd)
    if (header_before.st_dev, header_before.st_ino) != (
        header_opened.st_dev,
        header_opened.st_ino,
    ):
        raise SystemExit("ERROR: private token-header file changed while opening")
    os.ftruncate(header_fd, 0)
    header_payload = b"X-SF-Token: " + data + b"\n"
    if os.write(header_fd, header_payload) != len(header_payload):
        raise SystemExit("ERROR: private token-header file write was incomplete")
    os.fsync(header_fd)
finally:
    os.close(header_fd)
PY
    url="https://api.${APM_REALM}.observability.splunkcloud.com/v2/apm/topology"
    request_file="$(mktemp)"
    body_file="$(mktemp)"
    chmod 600 "${request_file}" "${body_file}"
    trap 'rm -f "${header_file}" "${request_file}" "${body_file}"' EXIT
    if ! "${PYTHON_BIN}" - "${OUTPUT_DIR}/metadata.json" "${CHECK_APM}" "${request_file}" <<'PY'
import json
import sys
from datetime import datetime, timedelta, timezone

metadata_path, service, output_path = sys.argv[1:]
metadata = json.load(open(metadata_path, encoding="utf-8"))
environment = str(metadata.get("deployment_environment") or "")
if not environment or any(character.isspace() or ord(character) < 0x20 for character in environment):
    raise SystemExit("ERROR: metadata.json has no safe deployment_environment for the APM query")
cluster_name = str(metadata.get("cluster_name") or "")
if not cluster_name or any(character.isspace() or ord(character) < 0x20 for character in cluster_name):
    raise SystemExit("ERROR: metadata.json has no safe cluster_name for the APM query")
if not service or service != service.strip() or any(ord(character) < 0x20 for character in service):
    raise SystemExit("ERROR: --check-apm requires a safe, nonempty service name")
end = datetime.now(timezone.utc)
start = end - timedelta(minutes=15)
milliseconds = lambda value: int(value.timestamp() * 1000)
payload = {
    "timeRange": f"{milliseconds(start)}/{milliseconds(end)}",
    "tagFilters": [
        {"name": "sf_service", "operator": "equals", "scope": "GLOBAL", "value": service},
        {"name": "sf_environment", "operator": "equals", "scope": "GLOBAL", "value": environment},
        {"name": "k8s.cluster.name", "operator": "equals", "scope": "GLOBAL", "value": cluster_name},
    ],
}
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
PY
    then
        log "ERROR: Could not build the scoped APM topology query."
        exit 1
    fi
    if ! curl -q --proto '=https' --tlsv1.2 -fsS \
        --connect-timeout 10 --max-time 60 \
        -H "@${header_file}" -H "Content-Type: application/json" \
        --data-binary "@${request_file}" -o "${body_file}" "${url}"; then
        log "ERROR: Splunk Observability APM topology API request failed."
        exit 1
    fi
    if ! "${PYTHON_BIN}" - "${body_file}" "${CHECK_APM}" <<'PY'
import json
import sys

path, expected = sys.argv[1:]
try:
    payload = json.load(open(path, encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"ERROR: APM topology response was not valid JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)


if not isinstance(payload, dict):
    print("ERROR: APM topology response was not a JSON object.", file=sys.stderr)
    raise SystemExit(1)
for error_key in ("error", "errors"):
    if payload.get(error_key) not in (None, "", [], {}):
        print("ERROR: APM topology response contains an explicit error payload.", file=sys.stderr)
        raise SystemExit(1)
if "data" in payload:
    if "nodes" in payload or "edges" in payload or not isinstance(payload["data"], dict):
        print("ERROR: APM topology response has an ambiguous data envelope.", file=sys.stderr)
        raise SystemExit(1)
    graph = payload["data"]
else:
    graph = payload
for error_key in ("error", "errors"):
    if graph.get(error_key) not in (None, "", [], {}):
        print("ERROR: APM topology data envelope contains an explicit error payload.", file=sys.stderr)
        raise SystemExit(1)
nodes = graph.get("nodes")
if not isinstance(nodes, list):
    print("ERROR: APM topology response has no nodes array.", file=sys.stderr)
    raise SystemExit(1)
matches = [
    node
    for node in nodes
    if isinstance(node, dict)
    and node.get("serviceName") == expected
    and node.get("type") == "service"
]
if not matches:
    print(
        f"ERROR: instrumented service node {expected!r} is not visible in the scoped APM topology response.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
    then
        exit 1
    fi
    rm -f "${header_file}" "${request_file}" "${body_file}"
    trap - EXIT
    log "  APM topology contains '${CHECK_APM}'."
fi

if [[ "${CHECK_BACKUP}" == "true" ]]; then
    log "Live: --check-backup"
    backup_args=(--mode verify --metadata "${OUTPUT_DIR}/metadata.json" --target-all)
    if [[ -n "${KUBE_CONTEXT}" ]]; then backup_args+=(--kube-context "${KUBE_CONTEXT}"); fi
    if ! "${PYTHON_BIN}" "${OUTPUT_DIR}/k8s-instrumentation/annotation-backup.py" "${backup_args[@]}"; then
        log "ERROR: transactional rollback snapshot validation failed."
        exit 1
    fi
fi

log "Validation complete."
