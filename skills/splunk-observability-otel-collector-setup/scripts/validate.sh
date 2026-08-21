#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-otel-rendered"
CHECK_K8S=false
CHECK_LINUX=false
CHECK_TA=false
CHECK_PLATFORM_HEC=false
LIVE=false
K8S_WORKLOADS_ONLY=false
CHECK_UPSTREAM=false
EXECUTION="local"
KUBE_CONTEXT=""

usage() {
    cat <<'EOF'
Splunk Observability OTel Collector validation

Usage:
  bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR       Rendered output directory
  --check-k8s            Check Kubernetes rendered assets
  --check-linux          Check Linux rendered assets
  --check-ta             Check Splunkbase 7125 TA rendered assets
  --check-platform-hec   Check rendered Splunk Platform HEC helper assets
  --live                 Run live status checks using rendered status scripts
  --k8s-workloads-only   With live Kubernetes validation, avoid Helm release Secret reads
  --kube-context CTX     Context for --k8s-workloads-only kubectl reads
  --check-upstream       Download/pull pinned upstream artifacts and template them
  --execution local|ssh  Linux live validation mode (default: local)
  --help                 Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --check-k8s) CHECK_K8S=true; shift ;;
        --check-linux) CHECK_LINUX=true; shift ;;
        --check-ta) CHECK_TA=true; shift ;;
        --check-platform-hec) CHECK_PLATFORM_HEC=true; shift ;;
        --live) LIVE=true; shift ;;
        --k8s-workloads-only) K8S_WORKLOADS_ONLY=true; CHECK_K8S=true; LIVE=true; shift ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --check-upstream) CHECK_UPSTREAM=true; shift ;;
        --execution) require_arg "$1" "$#" || exit 1; EXECUTION="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

case "${EXECUTION}" in
    local|ssh) ;;
    *)
        log "ERROR: --execution must be local or ssh."
        exit 1
        ;;
esac

if [[ "${CHECK_K8S}" != "true" && "${CHECK_LINUX}" != "true" && "${CHECK_TA}" != "true" && "${CHECK_PLATFORM_HEC}" != "true" ]]; then
    [[ -d "${OUTPUT_DIR}/k8s" ]] && CHECK_K8S=true
    [[ -d "${OUTPUT_DIR}/linux" ]] && CHECK_LINUX=true
    [[ -d "${OUTPUT_DIR}/ta" ]] && CHECK_TA=true
    [[ -d "${OUTPUT_DIR}/platform-hec" ]] && CHECK_PLATFORM_HEC=true
fi

if [[ "${CHECK_K8S}" != "true" && "${CHECK_LINUX}" != "true" && "${CHECK_TA}" != "true" && "${CHECK_PLATFORM_HEC}" != "true" ]]; then
    log "ERROR: No rendered Kubernetes, Linux, TA, or Splunk Platform HEC assets found under ${OUTPUT_DIR}."
    exit 1
fi

check_file() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        log "ERROR: Missing ${path}"
        exit 1
    fi
}

check_shell_tree() {
    local directory="$1" script
    while IFS= read -r -d '' script; do
        bash -n "${script}" || {
            log "ERROR: Rendered script failed shell syntax validation: ${script}"
            exit 1
        }
    done < <(find "${directory}" -type f -name '*.sh' -print0)
}

check_python_tree() {
    local directory="$1" script
    while IFS= read -r -d '' script; do
        python3 -c 'import pathlib,sys; path=pathlib.Path(sys.argv[1]); compile(path.read_text(encoding="utf-8"), str(path), "exec")' "${script}" || {
            log "ERROR: Rendered Python failed syntax validation: ${script}"
            exit 1
        }
    done < <(find "${directory}" -type f -name '*.py' -print0)
}

if [[ "${CHECK_K8S}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/k8s/values.yaml"
    check_file "${OUTPUT_DIR}/k8s/create-secret.sh"
    check_file "${OUTPUT_DIR}/k8s/helm-install.sh"
    check_file "${OUTPUT_DIR}/k8s/preflight.sh"
    check_file "${OUTPUT_DIR}/k8s/validate-secrets.sh"
    check_file "${OUTPUT_DIR}/k8s/verify-overlays.sh"
    check_file "${OUTPUT_DIR}/k8s/verify-overlay.py"
    check_file "${OUTPUT_DIR}/k8s/fetch-chart.sh"
    check_file "${OUTPUT_DIR}/k8s/k8s-image-post-renderer.py"
    check_file "${OUTPUT_DIR}/k8s/helm-plugins/splunk-audited-image-pin/plugin.yaml"
    check_file "${OUTPUT_DIR}/k8s/helm-plugins/splunk-audited-image-pin/run.sh"
    check_file "${OUTPUT_DIR}/k8s/verify-supply-chain.sh"
    check_file "${OUTPUT_DIR}/k8s/redact-stream.py"
    check_file "${OUTPUT_DIR}/k8s/verify-secret-revision.py"
    check_file "${OUTPUT_DIR}/k8s/helm-release-guard.py"
    check_file "${OUTPUT_DIR}/k8s/k8s-object-preconditions.py"
    check_file "${OUTPUT_DIR}/k8s/add-secret-ownership.py"
    check_file "${OUTPUT_DIR}/k8s/secret-revision-values.yaml"
    check_file "${OUTPUT_DIR}/k8s/cleanup-secret.sh"
    check_file "${OUTPUT_DIR}/k8s/status.sh"
    check_file "${OUTPUT_DIR}/k8s/uninstall.sh"
    check_shell_tree "${OUTPUT_DIR}/k8s"
    check_python_tree "${OUTPUT_DIR}/k8s"
    bash "${OUTPUT_DIR}/k8s/verify-overlays.sh"
    bash "${OUTPUT_DIR}/k8s/verify-supply-chain.sh"
    grep -q '^overlay_names=(' "${OUTPUT_DIR}/k8s/verify-overlays.sh" &&
    grep -Eq '^[[:space:]]*values\.yaml[[:space:]]*$' "${OUTPUT_DIR}/k8s/verify-overlays.sh" || {
        log "ERROR: Kubernetes base values must be integrity-bound before Helm use."
        exit 1
    }
    grep -q 'SPLUNK_OTEL_CONFIRM_SECRET_DELETE' "${OUTPUT_DIR}/k8s/cleanup-secret.sh" || {
        log "ERROR: retained Secret cleanup must require explicit confirmation."
        exit 1
    }
    for script in create-secret.sh cleanup-secret.sh; do
        grep -q 'splunk.com/owner-skill' "${OUTPUT_DIR}/k8s/${script}" || {
            log "ERROR: ${script} must enforce exact Collector Secret ownership."
            exit 1
        }
    done
    for script in preflight.sh helm-install.sh status.sh uninstall.sh; do
        grep -q 'query_helm_release' "${OUTPUT_DIR}/k8s/${script}" || {
            log "ERROR: ${script} must reject foreign same-name Helm releases."
            exit 1
        }
    done
    grep -q 'must not contain NUL or newline bytes' "${OUTPUT_DIR}/k8s/validate-secrets.sh" || {
        log "ERROR: Kubernetes token validation must explicitly reject NUL and newline bytes."
        exit 1
    }
    grep -q 'mktemp "${script_dir}/.secret-revision-values.XXXXXX"' "${OUTPUT_DIR}/k8s/create-secret.sh" || {
        log "ERROR: Secret revision overlay updates must use a same-directory exclusive temporary file."
        exit 1
    }
    if [[ -f "${OUTPUT_DIR}/k8s/priority-class.sh" ]]; then
        check_file "${OUTPUT_DIR}/k8s/cleanup-priority-class.sh"
        grep -q 'splunk.com/owner-skill' "${OUTPUT_DIR}/k8s/priority-class.sh" || {
            log "ERROR: PriorityClass apply must attach ownership metadata."
            exit 1
        }
        grep -q 'SPLUNK_OTEL_CONFIRM_PRIORITY_CLASS_DELETE' "${OUTPUT_DIR}/k8s/cleanup-priority-class.sh" || {
            log "ERROR: PriorityClass cleanup must require explicit confirmation."
            exit 1
        }
    fi
    if [[ -f "${OUTPUT_DIR}/k8s/instrumentation-lifecycle.py" ]]; then
        grep -q 'capture_instrumentation_prestate' "${OUTPUT_DIR}/k8s/helm-install.sh" &&
        grep -q 'rollback_instrumentation' "${OUTPUT_DIR}/k8s/helm-install.sh" &&
        grep -q 'helm_expected_revision' "${OUTPUT_DIR}/k8s/helm-install.sh" &&
        grep -q 'rollback_helm_mutation' "${OUTPUT_DIR}/k8s/helm-install.sh" &&
        grep -q -- '--verify-owned' "${OUTPUT_DIR}/k8s/preflight.sh" &&
        grep -q -- '--verify-owned' "${OUTPUT_DIR}/k8s/uninstall.sh" || {
            log "ERROR: Job-owned Instrumentation must enforce ownership and atomic prestate restore."
            exit 1
        }
    fi
    # Tolerant of YAML reformatting: any indentation, optional whitespace around
    # the boolean. Without this, a future yamllint reflow would break validation
    # without changing semantics.
    grep -Eq '^[[:space:]]+create:[[:space:]]*false([[:space:]]|$)' "${OUTPUT_DIR}/k8s/values.yaml" || {
        log "ERROR: Kubernetes values must use externally-created file-backed secrets."
        exit 1
    }
    python3 - "${PROJECT_ROOT}" "${OUTPUT_DIR}/k8s/values.yaml" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, str(Path(sys.argv[1]) / "skills" / "shared" / "lib"))
from yaml_compat import load_yaml_or_json

payload = load_yaml_or_json(Path(sys.argv[2]).read_text(encoding="utf-8"), source=sys.argv[2])
assert isinstance(payload, dict), "values.yaml must contain a mapping"
assert payload.get("secret", {}).get("create") is False, "secret.create must remain false"
o11y = payload.get("splunkObservability")
platform = payload.get("splunkPlatform")
assert isinstance(o11y, dict) or isinstance(platform, dict), "at least one destination must be configured"
if isinstance(o11y, dict):
    assert o11y.get("realm"), "Observability destination requires a realm"
    assert o11y.get("accessToken", "") == "", "Observability token must be external"
if isinstance(platform, dict):
    assert platform.get("token", "") == "", "Platform token must be external"
PY
    log "Kubernetes rendered assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        if [[ "${K8S_WORKLOADS_ONLY}" == "true" ]]; then
            command -v kubectl >/dev/null 2>&1 || {
                log "ERROR: kubectl is required for --k8s-workloads-only."
                exit 1
            }
            workload_args=(
                --metadata "${OUTPUT_DIR}/metadata.json"
                --image-verifier "${OUTPUT_DIR}/k8s/k8s-image-post-renderer.py"
            )
            if [[ -n "${KUBE_CONTEXT}" ]]; then
                workload_args+=(--kube-context "${KUBE_CONTEXT}")
            fi
            python3 "${SCRIPT_DIR}/validate_k8s_workloads.py" "${workload_args[@]}"
        else
            bash "${OUTPUT_DIR}/k8s/status.sh"
        fi
    fi
fi

if [[ "${CHECK_PLATFORM_HEC}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/platform-hec/render-hec-service.sh"
    check_file "${OUTPUT_DIR}/platform-hec/apply-hec-service.sh"
    check_file "${OUTPUT_DIR}/platform-hec/status-hec-service.sh"
    check_file "${OUTPUT_DIR}/platform-hec/README.md"
    grep -q 'splunk-hec-service-setup/scripts/setup.sh' "${OUTPUT_DIR}/platform-hec/render-hec-service.sh" || {
        log "ERROR: HEC helper must delegate to splunk-hec-service-setup."
        exit 1
    }
    grep -Eq -- '--token-file|--write-token-file' "${OUTPUT_DIR}/platform-hec/apply-hec-service.sh" || {
        log "ERROR: HEC helper must use file-based token handling."
        exit 1
    }
    log "Splunk Platform HEC helper assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        bash "${OUTPUT_DIR}/platform-hec/status-hec-service.sh"
    fi
fi

if [[ "${CHECK_TA}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/ta/README.md"
    check_file "${OUTPUT_DIR}/ta/metadata.json"
    check_file "${OUTPUT_DIR}/ta/package-audit.md"
    check_file "${OUTPUT_DIR}/ta/local/inputs.conf.template"
    check_file "${OUTPUT_DIR}/ta/preflight-ta.sh"
    check_file "${OUTPUT_DIR}/ta/stage-ta-package.sh"
    check_file "${OUTPUT_DIR}/ta/manage-backups.py"
    check_file "${OUTPUT_DIR}/ta/inventory-backups.sh"
    check_file "${OUTPUT_DIR}/ta/prune-backups.sh"
    check_file "${OUTPUT_DIR}/ta/apply-local-uf.sh"
    check_file "${OUTPUT_DIR}/ta/apply-deployment-server.sh"
    check_file "${OUTPUT_DIR}/ta/status-ta.sh"
    check_file "${OUTPUT_DIR}/ta/agent-management/render-serverclass-handoff.sh"
    check_shell_tree "${OUTPUT_DIR}/ta"
    check_python_tree "${OUTPUT_DIR}/ta"
    for script in \
        "${OUTPUT_DIR}/ta/preflight-ta.sh" \
        "${OUTPUT_DIR}/ta/stage-ta-package.sh" \
        "${OUTPUT_DIR}/ta/inventory-backups.sh" \
        "${OUTPUT_DIR}/ta/prune-backups.sh" \
        "${OUTPUT_DIR}/ta/apply-local-uf.sh" \
        "${OUTPUT_DIR}/ta/apply-deployment-server.sh" \
        "${OUTPUT_DIR}/ta/status-ta.sh" \
        "${OUTPUT_DIR}/ta/agent-management/render-serverclass-handoff.sh"; do
        bash -n "${script}" || {
            log "ERROR: TA rendered script failed shell syntax validation: ${script}"
            exit 1
        }
    done
    grep -q '"splunkbase_app_id": "7125"' "${OUTPUT_DIR}/ta/metadata.json" || {
        log "ERROR: TA metadata must identify Splunkbase app 7125."
        exit 1
    }
    python3 - "${OUTPUT_DIR}/ta/metadata.json" <<'PY'
import json
from pathlib import Path
import sys

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for package in metadata.get("packages", []):
    assert "sha256" in package, "TA package audit must record SHA-256"
    assert "dashboard_evidence" in package, "TA completion gate must record dashboard evidence"
PY
    grep -Eq '^\[Splunk_TA_otel://[^]]+\]' "${OUTPUT_DIR}/ta/local/inputs.conf.template" || {
        log "ERROR: TA inputs.conf.template must render a modular input stanza from inputs.conf.spec."
        exit 1
    }
    grep -q 'tarfile.open(fileobj=archive_handle' "${OUTPUT_DIR}/ta/stage-ta-package.sh" || {
        log "ERROR: TA staging must hash and extract through one open archive descriptor."
        exit 1
    }
    grep -q 'sys.version_info < (3, 6)' "${OUTPUT_DIR}/ta/preflight-ta.sh" &&
    grep -q 'O_NOFOLLOW.*O_DIRECTORY' "${OUTPUT_DIR}/ta/preflight-ta.sh" || {
        log "ERROR: TA preflight must gate its external Python version and no-follow directory capabilities."
        exit 1
    }
    grep -q 'sys.version_info < (3, 6)' "${OUTPUT_DIR}/ta/manage-backups.py" || {
        log "ERROR: standalone TA backup management must gate its Python runtime."
        exit 1
    }
    grep -q 'digest differs from the rendered review packet' "${OUTPUT_DIR}/ta/apply-deployment-server.sh" || {
        log "ERROR: TA apply must integrity-check generated overlay templates."
        exit 1
    }
    grep -q 'SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE' "${OUTPUT_DIR}/ta/prune-backups.sh" || {
        log "ERROR: TA backup pruning must be explicitly confirmation-gated."
        exit 1
    }
    if grep -R -E 'O11Y_SECRET_SHOULD_NOT|HEC_SECRET_SHOULD_NOT|SPLUNK_SECRET_SHOULD_NOT' "${OUTPUT_DIR}/ta" >/dev/null 2>&1; then
        log "ERROR: TA rendered assets appear to contain test token values."
        exit 1
    fi
    log "Splunk Add-On for OpenTelemetry Collector TA assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        bash "${OUTPUT_DIR}/ta/status-ta.sh"
    fi
fi

if [[ "${CHECK_LINUX}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/linux/install-local.sh"
    check_file "${OUTPUT_DIR}/linux/install-ssh.sh"
    check_file "${OUTPUT_DIR}/linux/remote-install.sh"
    check_file "${OUTPUT_DIR}/linux/preflight-local.sh"
    check_file "${OUTPUT_DIR}/linux/status-local.sh"
    check_file "${OUTPUT_DIR}/linux/status-ssh.sh"
    check_file "${OUTPUT_DIR}/linux/doctor-local.sh"
    check_file "${OUTPUT_DIR}/linux/doctor-ssh.sh"
    check_file "${OUTPUT_DIR}/linux/redact-stream.py"
    check_file "${OUTPUT_DIR}/linux/support-bundle-local.sh"
    check_file "${OUTPUT_DIR}/linux/support-bundle-ssh.sh"
    check_file "${OUTPUT_DIR}/linux/uninstall-local.sh"
    check_file "${OUTPUT_DIR}/linux/uninstall-ssh.sh"
    check_shell_tree "${OUTPUT_DIR}/linux"
    check_python_tree "${OUTPUT_DIR}/linux"
    grep -q 'INSTALLER_SHA256=' "${OUTPUT_DIR}/linux/install-local.sh" || {
        log "ERROR: Linux installer wrapper must pin and verify SHA-256."
        exit 1
    }
    if grep -R -E -- '--trace-url|--hec-url|remote_token=|header_file=' "${OUTPUT_DIR}/linux" >/dev/null; then
        log "ERROR: Linux assets contain a removed/deprecated flag or unsafe token-transfer behavior."
        exit 1
    fi
    python3 - "${OUTPUT_DIR}/linux" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
matches = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "VERIFY_ACCESS_TOKEN=false" in line:
            matches.append((path.name, number, line))
            assert path.name in {"install-local.sh", "remote-install.sh"}, matches[-1]
            assert "env VERIFY_ACCESS_TOKEN=false sh" in line, matches[-1]
assert len(matches) == 4, f"expected four narrowly scoped installer bypass calls, found: {matches}"
for name in ("install-local.sh", "remote-install.sh"):
    text = (root / name).read_text(encoding="utf-8")
    assert "--config -" in text, f"{name} must stream the token through curl config stdin"
    assert "curl -q --proto '=https'" in text, f"{name} must disable user curl configuration"
    assert "--write-out '%{http_code}'" in text, f"{name} must inspect the exact HTTP status"
    assert "expected 200" in text, f"{name} must require the upstream verifier's exact status"
    assert "--header @-" not in text, f"{name} must remain compatible with the oldest supported curl"
PY
    log "Linux rendered assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        if [[ "${EXECUTION}" == "ssh" ]]; then
            bash "${OUTPUT_DIR}/linux/status-ssh.sh"
        else
            bash "${OUTPUT_DIR}/linux/status-local.sh"
        fi
    fi
fi

if [[ "${CHECK_UPSTREAM}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/metadata.json"
    command -v helm >/dev/null 2>&1 || { log "ERROR: helm is required for --check-upstream."; exit 1; }
    command -v curl >/dev/null 2>&1 || { log "ERROR: curl is required for --check-upstream."; exit 1; }
    if [[ "${CHECK_K8S}" == "true" ]]; then
        read -r chart_version release_name namespace < <(python3 -c 'import json,sys; data=json.load(open(sys.argv[1]))["kubernetes"]; print(data["chart_version"], data["release_name"], data["namespace"])' "${OUTPUT_DIR}/metadata.json")
        [[ "${chart_version}" == "0.158.0" ]] || { log "ERROR: chart version is outside the audited archive contract."; exit 1; }
        chart_archive="$(bash "${OUTPUT_DIR}/k8s/fetch-chart.sh")"
        helm_args=(-f "${OUTPUT_DIR}/k8s/values.yaml")
        while IFS= read -r file; do helm_args+=(-f "${file}"); done < <(find "${OUTPUT_DIR}/k8s" -maxdepth 1 -name 'extra-values-*.yaml' | sort)
        helm_args+=(-f "${OUTPUT_DIR}/k8s/secret-revision-values.yaml")
        helm_version="$(helm version --template '{{.Version}}')"
        [[ "${helm_version}" =~ ^v?([0-9]+)\. ]] || { log "ERROR: could not determine Helm major version."; exit 1; }
        if (( BASH_REMATCH[1] >= 4 )); then
            helm_command=(env "HELM_PLUGINS=${OUTPUT_DIR}/k8s/helm-plugins" helm)
            post_renderer_args=(--post-renderer splunk-audited-image-pin)
        else
            helm_command=(helm)
            post_renderer_args=(--post-renderer "${OUTPUT_DIR}/k8s/k8s-image-post-renderer.py")
        fi
        manifest="$(mktemp)"
        trap 'rm -f "${manifest}"' EXIT
        "${helm_command[@]}" template "${release_name}" "${chart_archive}" \
            --namespace "${namespace}" "${post_renderer_args[@]}" "${helm_args[@]}" >"${manifest}"
        python3 "${OUTPUT_DIR}/k8s/k8s-image-post-renderer.py" --verify "${manifest}"
        rm -f "${manifest}"
        trap - EXIT
    fi
    if [[ "${CHECK_LINUX}" == "true" ]]; then
        read -r installer_url installer_sha < <(python3 - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))["linux"]
print(data["installer_url"], data["installer_sha256"])
PY
)
        installer="$(mktemp)"
        trap 'rm -f "${installer}"' EXIT
        curl -q --proto '=https' --proto-redir '=https' --max-redirs 5 --globoff --tlsv1.2 --connect-timeout 10 --max-time 120 -fsSL "${installer_url}" -o "${installer}"
        if command -v sha256sum >/dev/null 2>&1; then
            actual="$(sha256sum "${installer}" | awk '{print $1}')"
        elif command -v shasum >/dev/null 2>&1; then
            actual="$(shasum -a 256 "${installer}" | awk '{print $1}')"
        else
            log "ERROR: sha256sum or shasum is required for installer verification."
            exit 1
        fi
        [[ "${actual}" == "${installer_sha}" ]] || { log "ERROR: pinned Linux installer digest changed."; exit 1; }
        sh "${installer}" --help 2>&1 | grep -q -- '--collector-version' || {
            log "ERROR: pinned Linux installer help contract is unexpected."
            exit 1
        }
    fi
    log "Pinned upstream artifact validation passed."
fi
