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
SKIP_APM_CHECK=false
SKIP_BACKUP_CHECK=false
KUBE_CONTEXT=""

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
  --check-apm SERVICE      Probe api.<realm>.observability.splunkcloud.com/v2/apm/topology
  --check-backup           Every rendered target has a valid rollback snapshot
  --skip-apm-check         With --live only, explicitly omit the APM telemetry gate
  --skip-backup-check      With --live only, explicitly omit rollback-snapshot validation
  --kube-context CTX       Propagate to kubectl invocations
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
        --check-apm) require_arg "$1" "$#" || exit 1; CHECK_APM="$2"; LIVE=true; shift 2 ;;
        --check-backup) CHECK_BACKUP=true; LIVE=true; shift ;;
        --skip-apm-check) SKIP_APM_CHECK=true; shift ;;
        --skip-backup-check) SKIP_BACKUP_CHECK=true; shift ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
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
check_file "${OUTPUT_DIR}/k8s-instrumentation/workload-annotations.yaml"
check_file "${OUTPUT_DIR}/k8s-instrumentation/annotation-backup-configmap.yaml"
check_file "${OUTPUT_DIR}/k8s-instrumentation/preflight-report.md"
check_file "${OUTPUT_DIR}/runbook.md"

# Prefer repo-local venv python.
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)"
fi

log "Static: verifying YAML well-formedness and patch-target invariant."
"${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
import json
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR: PyYAML missing; install requirements-agent.txt", file=sys.stderr)
    raise SystemExit(1)

root = Path(sys.argv[1])
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

# Workload annotations must target spec.template.metadata.annotations, not
# top-level metadata.annotations. This is the single most common authoring
# bug in operator-driven auto-instrumentation; the static check enforces it.
wl_path = root / "k8s-instrumentation/workload-annotations.yaml"
for doc in load_all(wl_path):
    if not isinstance(doc, dict):
        continue
    if doc.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
        continue
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

# Scrub: no token-shaped strings in rendered scripts.
import re
token_re = re.compile(
    r"(?i)(access[_-]?token|api[_-]?token|bearer[_-]?token|hec[_-]?token|sf[_-]?token)"
    r"\s*[:=]\s*[A-Za-z0-9._-]{20,}"
)
for p in root.rglob("*.sh"):
    body = p.read_text(encoding="utf-8")
    if token_re.search(body):
        errors.append(f"{p}: rendered script appears to embed a token-shaped value.")

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
    "operator_resources",
):
    if key not in meta:
        errors.append(f"{meta_path}: missing required key '{key}'.")
if meta.get("skill") != "splunk-observability-k8s-auto-instrumentation-setup":
    errors.append(f"{meta_path}: unexpected skill identity {meta.get('skill')!r}.")
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

KUBECTL=(kubectl)
if [[ -n "${KUBE_CONTEXT}" ]]; then KUBECTL+=(--context "${KUBE_CONTEXT}"); fi

if [[ "${CHECK_WEBHOOK}" == "true" \
    || "${CHECK_INSTRUMENTATION}" == "true" \
    || "${CHECK_INJECTION}" == "true" \
    || "${CHECK_BACKUP}" == "true" ]]; then
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
    if ! "${KUBECTL[@]}" -n "${operator_namespace}" get endpoints \
        "${expected_webhook_service}" -o json >"${webhook_state_dir}/endpoints.json"; then
        log "ERROR: Kubernetes API failed while reading webhook Endpoints ${operator_namespace}/${expected_webhook_service}."
        exit 1
    fi
    if ! webhook_policy="$("${PYTHON_BIN}" - \
        "${webhook_state_dir}/webhook.json" \
        "${webhook_state_dir}/service.json" \
        "${webhook_state_dir}/endpoints.json" \
        "${expected_webhook}" "${expected_webhook_service}" "${operator_namespace}" <<'PY'
import base64
import binascii
import json
import re
import sys

webhook_path, service_path, endpoints_path, expected, service_name, namespace = sys.argv[1:]
webhook_obj = json.load(open(webhook_path, encoding="utf-8"))
service_obj = json.load(open(service_path, encoding="utf-8"))
endpoints_obj = json.load(open(endpoints_path, encoding="utf-8"))

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

endpoints_meta = endpoints_obj.get("metadata") or {}
if (
    endpoints_obj.get("kind") != "Endpoints"
    or endpoints_meta.get("name") != service_name
    or endpoints_meta.get("namespace") != namespace
):
    raise SystemExit("ERROR: Kubernetes returned different webhook Endpoints")
route_ready = any(
    bool(subset.get("addresses"))
    and any(
        port.get("name") in (None, "")
        and port.get("protocol", "TCP") == "TCP"
        and port.get("port") == 9443
        for port in (subset.get("ports") or [])
    )
    for subset in (endpoints_obj.get("subsets") or [])
)
if not route_ready:
    raise SystemExit(
        "ERROR: Operator webhook Service has no ready address on the pinned 9443/TCP endpoint port"
    )
print(failure_policy)
PY
    )"; then
        log "ERROR: Operator pod admission webhook is not route-ready."
        exit 1
    fi
    log "  MutatingWebhookConfiguration ${expected_webhook}: pod admission route ready (failurePolicy=${webhook_policy})."
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
    return {
        "apiVersion": document.get("apiVersion"),
        "kind": document.get("kind"),
        "metadata": {
            "name": metadata.get("name"),
            "namespace": metadata.get("namespace"),
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
    "${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR: PyYAML is required to validate language injection evidence.", file=sys.stderr)
    raise SystemExit(1)

root = Path(sys.argv[1])
meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
kube = json.loads(os.environ["KUBE_JSON"])
targets = meta.get("targets") or []
if not targets:
    print("ERROR: metadata.json contains no workload targets for --check-injection.", file=sys.stderr)
    sys.exit(1)

managed_prefix = "instrumentation.opentelemetry.io/"
language_spec_keys = {
    "java": "java",
    "nodejs": "nodejs",
    "python": "python",
    "dotnet": "dotnet",
    "go": "go",
    "apache-httpd": "apacheHttpd",
    "nginx": "nginx",
}
language_init_names = {
    "java": {"opentelemetry-auto-instrumentation-java"},
    "nodejs": {"opentelemetry-auto-instrumentation-nodejs"},
    "python": {"opentelemetry-auto-instrumentation-python"},
    "dotnet": {"opentelemetry-auto-instrumentation-dotnet"},
    "apache-httpd": {"otel-agent-source-container-clone", "otel-agent-attach-apache"},
    "nginx": {"otel-agent-source-container-clone", "otel-agent-attach-nginx"},
}
all_injected_init_names = set().union(*language_init_names.values())


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def managed_annotations(resource):
    return {
        str(key): str(value)
        for key, value in (resource or {}).items()
        if str(key).startswith(managed_prefix)
    }


cr_path = root / "k8s-instrumentation/instrumentation-cr.yaml"
cr_documents = [
    document
    for document in yaml.safe_load_all(cr_path.read_text(encoding="utf-8"))
    if isinstance(document, dict)
]
cr_by_identity = {
    (
        str((document.get("metadata") or {}).get("namespace") or ""),
        str((document.get("metadata") or {}).get("name") or ""),
    ): document
    for document in cr_documents
}
if len(cr_by_identity) != len(cr_documents) or not cr_documents:
    fail("instrumentation-cr.yaml has missing or duplicate Instrumentation CR identities")


def expected_endpoint(row, expected_annotations):
    language = str(row["language"])
    inject_key = f"{managed_prefix}inject-{language}"
    binding = str(expected_annotations.get(inject_key) or "")
    if binding == "false":
        return ""
    if binding == "true":
        candidates = [
            document
            for (namespace, _), document in cr_by_identity.items()
            if namespace == str(row["namespace"])
            and language_spec_keys[language] in (document.get("spec") or {})
        ]
    elif "/" in binding:
        namespace, name = binding.split("/", 1)
        document = cr_by_identity.get((namespace, name))
        candidates = [document] if document is not None else []
    else:
        fail(f"{row['target']} has invalid rendered {inject_key} value {binding!r}")
    if len(candidates) != 1:
        fail(f"{row['target']} does not resolve exactly one rendered {language} Instrumentation CR")
    document = candidates[0]
    language_block = (document.get("spec") or {}).get(language_spec_keys[language]) or {}
    language_env = {
        str(item.get("name") or ""): str(item.get("value") or "")
        for item in (language_block.get("env") or [])
        if isinstance(item, dict)
    }
    endpoint = language_env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or str(
        (((document.get("spec") or {}).get("exporter") or {}).get("endpoint") or "")
    )
    if not endpoint:
        fail(f"{row['target']} rendered {language} Instrumentation CR has no OTLP endpoint")
    return endpoint


def env_value(container, name, context):
    matches = [item for item in (container.get("env") or []) if item.get("name") == name]
    if len(matches) != 1 or matches[0].get("valueFrom") is not None:
        fail(f"{context} does not have one literal {name} environment value")
    value = matches[0].get("value")
    if not isinstance(value, str) or not value:
        fail(f"{context} has an empty or non-literal {name} environment value")
    return value


def selected_containers(pod_spec, expected_annotations, context):
    regular = [
        container
        for container in (pod_spec.get("containers") or [])
        if container.get("name") != "opentelemetry-auto-instrumentation"
    ]
    original_init = [
        container
        for container in (pod_spec.get("initContainers") or [])
        if container.get("name") not in all_injected_init_names
    ]
    configured = str(
        expected_annotations.get(f"{managed_prefix}container-names") or ""
    )
    if configured:
        names = [name.strip() for name in configured.split(",") if name.strip()]
        if not names or len(names) != len(set(names)):
            fail(f"{context} has invalid rendered container-names annotation")
        by_name = {
            str(container.get("name") or ""): container
            for container in [*regular, *original_init]
        }
        missing = [name for name in names if name not in by_name]
        if missing:
            fail(f"{context} is missing annotated target container(s): {', '.join(missing)}")
        return [by_name[name] for name in names]
    if not regular:
        fail(f"{context} has no application container to validate")
    return [regular[0]]


def volume_mount_names(container):
    return {str(item.get("name") or "") for item in (container.get("volumeMounts") or [])}


def require_endpoint(container, endpoint, context):
    actual = env_value(container, "OTEL_EXPORTER_OTLP_ENDPOINT", context)
    if actual != endpoint:
        fail(f"{context} OTEL_EXPORTER_OTLP_ENDPOINT does not match the rendered Instrumentation CR")


def verify_language_evidence(row, pod, expected_annotations):
    language = str(row["language"])
    pod_name = str((pod.get("metadata") or {}).get("name") or "<unknown>")
    context = f"pod {row['namespace']}/{pod_name} for {row['kind']}/{row['name']}"
    pod_spec = pod.get("spec") or {}
    init_names = {
        str(container.get("name") or "")
        for container in (pod_spec.get("initContainers") or [])
    }
    inject_key = f"{managed_prefix}inject-{language}"
    enabled = expected_annotations.get(inject_key) != "false"
    required_init = language_init_names.get(language, set())
    if not enabled:
        stale = sorted(required_init & init_names)
        if language == "go" and any(
            container.get("name") == "opentelemetry-auto-instrumentation"
            for container in (pod_spec.get("containers") or [])
        ):
            stale.append("opentelemetry-auto-instrumentation")
        if stale:
            fail(f"{context} retains disabled {language} injection artifacts: {', '.join(stale)}")
        return

    endpoint = expected_endpoint(row, expected_annotations)
    if language == "go":
        selected = selected_containers(pod_spec, expected_annotations, context)
        if len(selected) != 1:
            fail(f"{context} Go injection must target exactly one application container")
        sidecars = [
            container
            for container in (pod_spec.get("containers") or [])
            if container.get("name") == "opentelemetry-auto-instrumentation"
        ]
        if len(sidecars) != 1:
            fail(f"{context} does not have exactly one Go auto-instrumentation sidecar")
        sidecar = sidecars[0]
        if pod_spec.get("shareProcessNamespace") is not True:
            fail(f"{context} Go injection does not enable shareProcessNamespace")
        security = sidecar.get("securityContext") or {}
        if security.get("privileged") is not True or security.get("runAsUser") != 0:
            fail(f"{context} Go sidecar lacks the rendered Operator privilege evidence")
        expected_exe = str(
            expected_annotations.get(f"{managed_prefix}otel-go-auto-target-exe") or ""
        )
        if env_value(sidecar, "OTEL_GO_AUTO_TARGET_EXE", context) != expected_exe:
            fail(f"{context} Go target executable does not match the rendered annotation")
        require_endpoint(sidecar, endpoint, context)
        return

    missing_init = sorted(required_init - init_names)
    if missing_init:
        fail(f"{context} lacks exact {language} init container(s): {', '.join(missing_init)}")

    for container in selected_containers(pod_spec, expected_annotations, context):
        container_name = str(container.get("name") or "<unknown>")
        container_context = f"{context} container {container_name}"
        require_endpoint(container, endpoint, container_context)
        if language == "java":
            value = env_value(container, "JAVA_TOOL_OPTIONS", container_context)
            expected_agent = (
                f"-javaagent:/otel-auto-instrumentation-java-{container_name}/javaagent.jar"
            )
            if expected_agent not in value.split():
                fail(f"{container_context} lacks the exact Java agent option {expected_agent}")
        elif language == "nodejs":
            value = env_value(container, "NODE_OPTIONS", container_context)
            if "--require /otel-auto-instrumentation-nodejs/autoinstrumentation.js" not in value:
                fail(f"{container_context} lacks the OpenTelemetry Node.js require hook")
        elif language == "python":
            value = env_value(container, "PYTHONPATH", container_context)
            required_paths = {
                "/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation",
                "/otel-auto-instrumentation-python",
            }
            if not required_paths.issubset(set(value.split(":"))):
                fail(f"{container_context} lacks the OpenTelemetry Python paths")
        elif language == "dotnet":
            expected_values = {
                "CORECLR_ENABLE_PROFILING": "1",
                "CORECLR_PROFILER": "{918728DD-259F-4A6A-AC2B-B85E1B658318}",
                "OTEL_DOTNET_AUTO_HOME": "/otel-auto-instrumentation-dotnet",
            }
            for name, expected in expected_values.items():
                if env_value(container, name, container_context) != expected:
                    fail(f"{container_context} has unexpected {name}")
            runtime = str(
                expected_annotations.get(f"{managed_prefix}otel-dotnet-auto-runtime")
                or "linux-x64"
            )
            library_dir = "linux-musl-x64" if runtime == "linux-musl-x64" else "linux-x64"
            expected_path = (
                f"/otel-auto-instrumentation-dotnet/{library_dir}/"
                "OpenTelemetry.AutoInstrumentation.Native.so"
            )
            if env_value(container, "CORECLR_PROFILER_PATH", container_context) != expected_path:
                fail(f"{container_context} CORECLR_PROFILER_PATH does not match {runtime}")
        elif language == "apache-httpd":
            required_mounts = {"otel-apache-agent", "otel-apache-conf-dir"}
            if not required_mounts.issubset(volume_mount_names(container)):
                fail(f"{container_context} lacks exact Apache agent/config volume mounts")
        elif language == "nginx":
            required_mounts = {"otel-nginx-agent", "otel-nginx-conf-dir"}
            if not required_mounts.issubset(volume_mount_names(container)):
                fail(f"{container_context} lacks exact Nginx agent/config volume mounts")
            library_path = env_value(container, "LD_LIBRARY_PATH", container_context)
            if "/opt/opentelemetry-webserver/agent/sdk_lib/lib" not in library_path.split(":"):
                fail(f"{container_context} lacks the OpenTelemetry Nginx library path")


def selector_matches(selector, labels):
    for key, value in (selector.get("matchLabels") or {}).items():
        if str(labels.get(key, "")) != str(value):
            return False
    for expr in selector.get("matchExpressions") or []:
        key = str(expr.get("key") or "")
        operator = str(expr.get("operator") or "")
        values = {str(value) for value in (expr.get("values") or [])}
        present = key in labels
        actual = str(labels.get(key, ""))
        if operator == "In" and (not present or actual not in values):
            return False
        if operator == "NotIn" and present and actual in values:
            return False
        if operator == "Exists" and not present:
            return False
        if operator == "DoesNotExist" and present:
            return False
        if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            return False
    return True


grouped_targets = {}
for row in targets:
    if not isinstance(row, dict):
        fail("metadata.json contains a non-object workload target")
    language = str(row.get("language") or "")
    if language not in language_spec_keys:
        fail(f"metadata.json contains unsupported target language {language!r}")
    identity = (str(row.get("kind") or ""), str(row.get("namespace") or ""), str(row.get("name") or ""))
    if not all(identity):
        fail("metadata.json contains a target with an incomplete identity")
    expected = row.get("annotations") or {}
    if not isinstance(expected, dict) or not expected:
        fail(f"{row.get('target') or '/'.join(identity)} has no rendered annotations in metadata.json")
    if any(not str(key).startswith(managed_prefix) for key in expected):
        fail(f"{row.get('target') or '/'.join(identity)} metadata contains an unmanaged annotation")
    group = grouped_targets.setdefault(identity, {"annotations": {}, "rows": []})
    for key, value in expected.items():
        key, value = str(key), str(value)
        if key in group["annotations"] and group["annotations"][key] != value:
            fail(f"{'/'.join(identity)} has conflicting rendered annotation values")
        group["annotations"][key] = value
    group["rows"].append(row)


for (kind, ns, name), group in grouped_targets.items():
    expected_annotations = group["annotations"]
    sel_proc = subprocess.run(
        kube + ["-n", ns, "get", kind.lower(), name, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if sel_proc.returncode != 0:
        print(f"ERROR: {kind}/{ns}/{name} lookup failed: {sel_proc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    try:
        workload = json.loads(sel_proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {kind}/{ns}/{name} returned invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    template_annotations = managed_annotations(
        (((workload.get("spec") or {}).get("template") or {}).get("metadata") or {}).get("annotations")
        or {}
    )
    if template_annotations != expected_annotations:
        fail(f"{kind}/{ns}/{name} managed pod-template annotations drifted from metadata.json")
    selector = ((workload.get("spec") or {}).get("selector") or {})
    if not selector.get("matchLabels") and not selector.get("matchExpressions"):
        print(f"ERROR: {kind}/{ns}/{name} has no usable pod selector.", file=sys.stderr)
        sys.exit(1)
    pods_args = kube + ["-n", ns, "get", "pods", "-o", "json"]
    pods_proc = subprocess.run(pods_args, capture_output=True, text=True)
    if pods_proc.returncode != 0:
        print(f"ERROR: pod lookup for {kind}/{ns}/{name} failed: {pods_proc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    try:
        pod_items = (json.loads(pods_proc.stdout or "{}") or {}).get("items", [])
    except json.JSONDecodeError as exc:
        print(f"ERROR: pod lookup for {kind}/{ns}/{name} returned invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    pods = [
        pod
        for pod in pod_items
        if not (pod.get("metadata") or {}).get("deletionTimestamp")
        and selector_matches(selector, (pod.get("metadata") or {}).get("labels") or {})
    ]
    if not pods:
        print(f"ERROR: {kind}/{ns}/{name} has no active pods matching its selector.", file=sys.stderr)
        sys.exit(1)
    for pod in pods:
        pod_name = str((pod.get("metadata") or {}).get("name") or "<unknown>")
        pod_annotations = managed_annotations((pod.get("metadata") or {}).get("annotations") or {})
        if pod_annotations != expected_annotations:
            fail(f"pod {ns}/{pod_name} managed annotations drifted from metadata.json")
        for row in group["rows"]:
            verify_language_evidence(row, pod, expected_annotations)
    languages = ",".join(sorted(str(row["language"]) for row in group["rows"]))
    print(
        f"  {kind}/{ns}/{name}: exact managed annotations and {languages} evidence "
        f"on {len(pods)} pod(s)"
    )
PY
fi

if [[ -n "${CHECK_APM}" ]]; then
    log "Live: --check-apm ${CHECK_APM}"
    if [[ -z "${SPLUNK_O11Y_REALM:-}" || -z "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
        log "ERROR: SPLUNK_O11Y_REALM and SPLUNK_O11Y_TOKEN_FILE are required for --check-apm."
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
    url="https://api.${SPLUNK_O11Y_REALM}.observability.splunkcloud.com/v2/apm/topology"
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


nodes = payload.get("nodes")
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
    "${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
kube = json.loads(os.environ["KUBE_JSON"])
name = meta.get("backup_configmap", "splunk-otel-auto-instrumentation-annotations-backup")
ns = meta.get("namespace", "splunk-otel")
proc = subprocess.run(kube + ["-n", ns, "get", "configmap", name, "-o", "json"], capture_output=True, text=True)
if proc.returncode != 0:
    print(f"ERROR: backup ConfigMap {ns}/{name} missing; annotations have not been applied yet.", file=sys.stderr)
    sys.exit(1)
try:
    obj = json.loads(proc.stdout)
except json.JSONDecodeError as exc:
    print(f"ERROR: backup ConfigMap {ns}/{name} returned invalid JSON: {exc}", file=sys.stderr)
    sys.exit(1)
data = obj.get("data") or {}
targets = meta.get("targets") or []
if not targets:
    print("ERROR: metadata.json contains no workload targets for --check-backup.", file=sys.stderr)
    sys.exit(1)
for target in targets:
    key = str(target.get("key") or "")
    identity = str(target.get("target") or key or "<unknown>")
    if not key or key not in data:
        print(f"ERROR: backup ConfigMap {ns}/{name} has no snapshot for {identity} ({key}).", file=sys.stderr)
        sys.exit(1)
    try:
        snapshot = json.loads(data[key])
    except (TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: backup snapshot {key} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(snapshot, dict):
        print(f"ERROR: backup snapshot {key} is not an annotation JSON object.", file=sys.stderr)
        sys.exit(1)
print(f"  backup {ns}/{name}: all {len(targets)} rendered workload snapshot(s) present")
PY
fi

log "Validation complete."
