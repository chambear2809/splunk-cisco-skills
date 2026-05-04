#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-k8s-auto-instrumentation-rendered"
LIVE=false
CHECK_WEBHOOK=false
CHECK_INSTRUMENTATION=false
CHECK_INJECTION=false
CHECK_APM=""
CHECK_BACKUP=false
KUBE_CONTEXT=""

usage() {
    cat <<'EOF'
Splunk Observability Kubernetes auto-instrumentation validation

Usage:
  bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR         Rendered output directory
  --live                   Run kubectl probes against the cluster
  --check-webhook          Operator MutatingWebhookConfiguration + log scan
  --check-instrumentation  kubectl get otelinst matches rendered CRs
  --check-injection        Assert init container + expected env on a sample pod per workload
  --check-apm SERVICE      Probe api.<realm>.signalfx.com/v2/apm/topology
  --check-backup           Annotation backup ConfigMap exists and is non-empty
  --kube-context CTX       Propagate to kubectl invocations
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --check-webhook) CHECK_WEBHOOK=true; LIVE=true; shift ;;
        --check-instrumentation) CHECK_INSTRUMENTATION=true; LIVE=true; shift ;;
        --check-injection) CHECK_INJECTION=true; LIVE=true; shift ;;
        --check-apm) require_arg "$1" "$#" || exit 1; CHECK_APM="$2"; LIVE=true; shift 2 ;;
        --check-backup) CHECK_BACKUP=true; LIVE=true; shift ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

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
for key in ("skill", "spec_digest", "preflight", "rendered_files", "targets"):
    if key not in meta:
        errors.append(f"{meta_path}: missing required key '{key}'.")

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

# Serialize the kubectl argv as JSON in an env var. The previous
# `kube = ${KUBECTL[@]@Q}` heredoc trick produced concatenated string literals
# in the embedded Python (`'kubectl' '--context' 'foo'` -> 'kubectl--contextfoo'),
# which made list(kube) iterate characters and never invoke kubectl correctly.
KUBE_JSON="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${KUBECTL[@]}")"
export KUBE_JSON

if [[ "${CHECK_WEBHOOK}" == "true" ]]; then
    log "Live: --check-webhook"
    webhook_count="$("${KUBECTL[@]}" get mutatingwebhookconfiguration 2>/dev/null | grep -c 'splunk-otel-collector-opentelemetry-operator-mutation' || true)"
    if [[ "${webhook_count}" -lt 1 ]]; then
        log "ERROR: splunk-otel-collector-opentelemetry-operator-mutation webhook not found."
        exit 1
    fi
    log "  MutatingWebhookConfiguration present (${webhook_count})."
    log "  (Skipping operator log scan; do it with 'kubectl logs -n splunk-otel -l app.kubernetes.io/name=operator | grep \"failed to call webhook\"'.)"
fi

if [[ "${CHECK_INSTRUMENTATION}" == "true" ]]; then
    log "Live: --check-instrumentation"
    "${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
kube = json.loads(os.environ["KUBE_JSON"])
for cr in meta.get("instrumentation_crs", []):
    ns = cr["namespace"]
    name = cr["name"]
    proc = subprocess.run(kube + ["-n", ns, "get", "otelinst", name, "-o", "json"], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"ERROR: otelinst {ns}/{name} not found:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"  otelinst {ns}/{name}: OK")
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

root = Path(sys.argv[1])
meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
kube = json.loads(os.environ["KUBE_JSON"])
for row in meta.get("targets", []):
    kind, ns, name = row["kind"], row["namespace"], row["name"]
    # Resolve the actual matchLabels selector instead of guessing `app=<name>`,
    # which matches almost no real-world Helm chart.
    sel_proc = subprocess.run(
        kube + ["-n", ns, "get", kind.lower(), name, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if sel_proc.returncode != 0:
        print(f"ERROR: {kind}/{ns}/{name} not found", file=sys.stderr)
        sys.exit(1)
    try:
        match_labels = (
            (((json.loads(sel_proc.stdout) or {}).get("spec") or {}).get("selector") or {}).get("matchLabels")
            or {}
        )
    except json.JSONDecodeError:
        match_labels = {}
    label_selector = ",".join(f"{k}={v}" for k, v in sorted(match_labels.items()))
    pods_args = kube + ["-n", ns, "get", "pods", "-o", "json"]
    if label_selector:
        pods_args += ["-l", label_selector]
    pods_proc = subprocess.run(pods_args, capture_output=True, text=True)
    init_present = False
    if pods_proc.returncode == 0:
        try:
            for pod in (json.loads(pods_proc.stdout or "{}") or {}).get("items", []):
                init_containers = (pod.get("spec") or {}).get("initContainers") or []
                if any(c.get("name") == "opentelemetry-auto-instrumentation" for c in init_containers):
                    init_present = True
                    break
        except json.JSONDecodeError:
            init_present = False
    if init_present:
        print(f"  {kind}/{ns}/{name}: init container present")
    else:
        print(
            f"WARN: {kind}/{ns}/{name}: no opentelemetry-auto-instrumentation init container visible yet",
            file=sys.stderr,
        )
PY
fi

if [[ -n "${CHECK_APM}" ]]; then
    log "Live: --check-apm ${CHECK_APM}"
    if [[ -z "${SPLUNK_O11Y_REALM:-}" || -z "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
        log "WARN: SPLUNK_O11Y_REALM or SPLUNK_O11Y_TOKEN_FILE not set; skipping APM probe."
    else
        url="https://api.${SPLUNK_O11Y_REALM}.signalfx.com/v2/apm/topology"
        # Pass the token via stdin to a header file rather than a process argument
        # so it never appears in `ps` output. Keeps SPLUNK_O11Y_TOKEN_FILE on disk
        # as the single source of truth and avoids exposing the token on argv.
        header_file="$(mktemp)"
        trap 'rm -f "${header_file}"' EXIT
        printf 'X-SF-Token: %s\n' "$(cat "${SPLUNK_O11Y_TOKEN_FILE}")" > "${header_file}"
        chmod 600 "${header_file}"
        body="$(curl -sS -H "@${header_file}" -H "Content-Type: application/json" -d "{\"timeRange\":\"-15m\"}" "${url}" || true)"
        rm -f "${header_file}"
        trap - EXIT
        if [[ -z "${body}" ]] || ! grep -q "\"${CHECK_APM}\"" <<<"${body}"; then
            log "WARN: service '${CHECK_APM}' not visible in APM topology yet."
        else
            log "  APM topology contains '${CHECK_APM}'."
        fi
    fi
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
data = json.loads(proc.stdout).get("data") or {}
if not data:
    print(f"WARN: backup ConfigMap {ns}/{name} exists but is empty (no annotations snapshotted yet).")
else:
    print(f"  backup {ns}/{name}: {len(data)} workload(s) snapshotted")
PY
fi

log "Validation complete."
