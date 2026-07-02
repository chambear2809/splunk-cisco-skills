#!/usr/bin/env bats
# Tests for Splunk Observability OTel Collector setup shell entrypoints.

bats_require_minimum_version 1.5.0

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    TMP_ROOT="$(mktemp -d)"
    O11Y_TOKEN_FILE="${TMP_ROOT}/o11y.token"
    HEC_TOKEN_FILE="${TMP_ROOT}/hec.token"
    printf '%s' 'O11Y_SECRET_SHOULD_NOT_LEAK' > "${O11Y_TOKEN_FILE}"
    printf '%s' 'HEC_SECRET_SHOULD_NOT_LEAK' > "${HEC_TOKEN_FILE}"
    # New: token-perm preflight requires mode 600. Honor it so existing
    # apply tests still pass after the hardening was added.
    chmod 600 "${O11Y_TOKEN_FILE}" "${HEC_TOKEN_FILE}"
}

teardown() {
    rm -rf "${TMP_ROOT}"
}

write_mock_command() {
    local name="$1"
    cat > "${TMP_ROOT}/bin/${name}" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cmd_name="$(basename "$0")"
printf '%s %s\n' "${cmd_name}" "$*" >> "${OTEL_CMD_LOG}"

if [[ "${cmd_name}" == "kubectl" && " $* " == *" get secret "* ]]; then
  exit 0
fi
if [[ "${cmd_name}" == "kubectl" && "${1:-}" == "create" && "${2:-}" == "secret" ]]; then
  printf '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"%s","namespace":"%s"},"data":{"mock":"bW9jaw=="}}\n' "${4:-}" "${6:-}"
fi
if [[ "${cmd_name}" == "kubectl" && "$*" == *"apply --server-side"* ]]; then
  cat >/dev/null
fi
if [[ "${cmd_name}" == "kubectl" && ( "$*" == *"create -f -"* || "$*" == *"replace -f -"* ) ]]; then
  cat >/dev/null
fi
if [[ "${cmd_name}" == "kubectl" && "$*" == *"auth can-i"* ]]; then
  printf 'yes\n'
fi
if [[ "${cmd_name}" == "kubectl" && "$*" == *"get pods"* && "$*" == *"-o name"* ]]; then
  printf 'pod/mock-collector\n'
fi
if [[ "${cmd_name}" == "kubectl" && "$*" == *"get daemonset splunk-otel-collector-agent -o json"* ]]; then
  cat <<'JSON'
{"apiVersion":"apps/v1","kind":"DaemonSet","metadata":{"name":"splunk-otel-collector-agent"},"spec":{"template":{"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410"}]}}}}
JSON
fi
if [[ "${cmd_name}" == "kubectl" && "$*" == *"get deployment splunk-otel-collector-k8s-cluster-receiver -o json"* ]]; then
  cat <<'JSON'
{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"splunk-otel-collector-k8s-cluster-receiver"},"spec":{"template":{"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410"}]}}}}
JSON
fi
if [[ "${cmd_name}" == "kubectl" && "$*" == *"get pods"* && "$*" == *"-o json"* ]]; then
  cat <<'JSON'
{"apiVersion":"v1","kind":"List","items":[{"apiVersion":"v1","kind":"Pod","metadata":{"name":"mock-collector"},"spec":{"containers":[{"name":"otel-collector","image":"quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410"}]}}]}
JSON
fi

if [[ "${cmd_name}" == "helm" && "${1:-}" == "template" ]]; then
  cat <<'YAML'
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: splunk-otel-collector-agent
spec:
  template:
    spec:
      containers:
      - name: otel-collector
        image: quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: splunk-otel-collector-k8s-cluster-receiver
spec:
  template:
    spec:
      containers:
      - name: otel-collector
        image: quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410
---
apiVersion: v1
kind: Pod
metadata:
  name: mock-validate-secret
spec:
  containers:
  - name: validate-secret
    image: registry.access.redhat.com/ubi9/ubi@sha256:8bf0e8f20737e9c8a68c8a498299e9504ab397b1b1f2837acb2fef12ec698f0e
YAML
fi
if [[ "${cmd_name}" == "helm" && "${1:-}" == "version" ]]; then
  printf 'v4.2.2\n'
fi
if [[ "${cmd_name}" == "helm" && "${1:-}" == "list" ]]; then
  if grep -q '^helm upgrade --install ' "${OTEL_CMD_LOG}"; then
    cat <<'JSON'
[{"name":"splunk-otel-collector","namespace":"splunk-otel","revision":"1","status":"deployed","chart":"splunk-otel-collector-0.154.0","app_version":"0.154.0"}]
JSON
  else
    printf '[]\n'
  fi
fi
if [[ "${cmd_name}" == "helm" && "${1:-}" == "get" && "${2:-}" == "all" ]]; then
  printf 'splunk-otel-collector\tsplunk-otel\t1\tdeployed\tsplunk-otel-collector\t0.154.0\n'
fi

if [[ "${cmd_name}" == "sha256sum" ]]; then
  if [[ "${1:-}" == *"splunk-otel-collector-0.154.0.tgz"* ]]; then
    printf '613f788d786bf741be770512c7c297c4b70d3ab5426ac337b0416209e66bc7b0  %s\n' "${1}"
    exit 0
  fi
  if [[ -f "${1:-}" ]] && grep -q "printf 'installer" "${1}" 2>/dev/null; then
    printf '16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29  %s\n' "${1}"
    exit 0
  fi
  if [[ -f "${1:-}" ]]; then
    python3 - "${1}" <<'PY'
import hashlib
from pathlib import Path
import sys

print(f"{hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()}  {sys.argv[1]}")
PY
    exit 0
  fi
  printf '16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29  %s\n' "${1:-installer}"
  exit 0
fi

if [[ "${cmd_name}" == "curl" ]]; then
  out=""
  write_out=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -o|--output) out="$2"; shift 2 ;;
      -w|--write-out) write_out="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  if [[ -n "${out}" && "${out}" != "/dev/null" ]]; then
    cat > "${out}" <<'INSTALLER'
#!/usr/bin/env sh
printf 'installer %s\n' "$*" >> "${OTEL_CMD_LOG}"
IFS= read -r token
[ -n "${token}" ]
INSTALLER
    chmod +x "${out}"
  fi
  if [[ -n "${write_out}" ]]; then
    printf '200'
  fi
fi

if [[ "${cmd_name}" == "sudo" ]]; then
  [[ "${1:-}" != "-n" ]] || shift
  if [[ "${1:-}" == "-u" ]]; then
    shift 2
  fi
  exec "$@"
fi

if [[ "${cmd_name}" == "id" && "${1:-}" == "-u" ]]; then
  printf '1000\n'
  exit 0
fi

if [[ "${cmd_name}" == "uname" && "${1:-}" == "-m" ]]; then
  printf 'x86_64\n'
  exit 0
fi

if [[ "${cmd_name}" == "ssh" ]]; then
  if [[ "$*" == *"mktemp -d /tmp/splunk-otel-install.XXXXXX"* ]]; then
    printf '/tmp/splunk-otel-install.ABC123\n'
  elif [[ "$*" == *"mktemp -d /tmp/splunk-otel-status.XXXXXX"* ]]; then
    printf '/tmp/splunk-otel-status.ABC123\n'
  elif [[ "$*" == *"remote-install.sh"* ]]; then
    IFS= read -r token
    [[ -n "${token}" ]]
  else
    cat >/dev/null
  fi
fi

exit 0
SH
    chmod +x "${TMP_ROOT}/bin/${name}"
}

make_mock_path() {
    mkdir -p "${TMP_ROOT}/bin"
    export OTEL_CMD_LOG="${TMP_ROOT}/commands.log"
    : > "${OTEL_CMD_LOG}"
    for cmd in kubectl helm aws curl sudo scp ssh sha256sum systemctl journalctl \
      systemd-tmpfiles getent groupadd useradd nologin apt-get id uname; do
        write_mock_command "${cmd}"
    done
    export PATH="${TMP_ROOT}/bin:${PATH}"
}

@test "observability otel render-only writes assets and does not run tools" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --render-k8s \
      --render-linux \
      --realm us0 \
      --cluster-name demo-cluster \
      --platform-hec-url https://splunk.example.com:8088/services/collector/event \
      --enable-logs \
      --platform-hec-token-file "${HEC_TOKEN_FILE}" \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/k8s/values.yaml" ]
    [ -f "${output_dir}/linux/install-local.sh" ]
    [ ! -s "${OTEL_CMD_LOG}" ]
    run ! grep -R "O11Y_SECRET_SHOULD_NOT_LEAK\\|HEC_SECRET_SHOULD_NOT_LEAK" "${output_dir}"
}

@test "observability otel renders platform hec helper without running hec setup" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --render-k8s \
      --render-platform-hec-helper \
      --realm us0 \
      --cluster-name demo-cluster \
      --platform-hec-url https://splunk.example.com:8088/services/collector/event \
      --enable-logs \
      --hec-platform cloud \
      --hec-token-name splunk_otel_k8s_logs \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/platform-hec/render-hec-service.sh" ]
    [ -f "${output_dir}/platform-hec/apply-hec-service.sh" ]
    grep -q "splunk-hec-service-setup/scripts/setup.sh" "${output_dir}/platform-hec/apply-hec-service.sh"
    grep -q -- "--write-token-file" "${output_dir}/platform-hec/apply-hec-service.sh"
    grep -q ".secrets/splunk_platform_hec_token" "${output_dir}/k8s/create-secret.sh"
    [ ! -s "${OTEL_CMD_LOG}" ]
}

@test "observability otel validates platform hec helper assets" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --render-platform-hec-helper \
      --realm us0 \
      --hec-platform enterprise \
      --hec-token-name splunk_otel_k8s_logs \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]

    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/validate.sh" \
      --check-platform-hec \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"Splunk Platform HEC helper assets passed static validation."* ]]
}

@test "observability otel apply k8s runs mocked kubectl and helm commands" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-k8s \
      --realm us0 \
      --cluster-name demo-cluster \
      --platform-hec-url https://splunk.example.com:8088/services/collector/event \
      --enable-logs \
      --platform-hec-token-file "${HEC_TOKEN_FILE}" \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    grep -q "kubectl create secret generic" "${OTEL_CMD_LOG}"
    grep -q "helm upgrade --install" "${OTEL_CMD_LOG}"
    run ! grep -q "O11Y_SECRET_SHOULD_NOT_LEAK\\|HEC_SECRET_SHOULD_NOT_LEAK" "${OTEL_CMD_LOG}"
}

@test "observability otel apply linux local feeds token through stdin path" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --render-linux \
      --realm us0 \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    printf '%s\n' 'ID="ubuntu"' 'VERSION_ID="22.04"' 'VERSION_CODENAME="jammy"' \
      > "${TMP_ROOT}/os-release"
    mkdir "${TMP_ROOT}/systemd-runtime"
    python3 - "${output_dir}/linux/preflight-local.sh" "${TMP_ROOT}/os-release" "${TMP_ROOT}/systemd-runtime" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("OS_RELEASE_FILE=/etc/os-release", f"OS_RELEASE_FILE='{sys.argv[2]}'")
text = text.replace("SYSTEMD_RUNTIME_DIR=/run/systemd/system", f"SYSTEMD_RUNTIME_DIR='{sys.argv[3]}'")
path.write_text(text, encoding="utf-8")
PY
    run bash "${output_dir}/linux/install-local.sh"
    [ "$status" -eq 0 ]
    run bash "${output_dir}/linux/status-local.sh"
    [ "$status" -eq 0 ]
    grep -q "curl .* -fsSL" "${OTEL_CMD_LOG}"
    grep -q "installer --realm us0" "${OTEL_CMD_LOG}"
    run ! grep -q "O11Y_SECRET_SHOULD_NOT_LEAK" "${OTEL_CMD_LOG}"
}

@test "observability otel apply linux ssh runs mocked scp and ssh commands" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-linux \
      --execution ssh \
      --linux-host otel.example.com \
      --ssh-user ec2-user \
      --realm us0 \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    grep -q "scp" "${OTEL_CMD_LOG}"
    grep -q "ssh -p 22 ec2-user@otel.example.com" "${OTEL_CMD_LOG}"
    run ! grep -q "VERIFY_ACCESS_TOKEN=false" "${OTEL_CMD_LOG}"
    run ! grep -q "O11Y_SECRET_SHOULD_NOT_LEAK" "${OTEL_CMD_LOG}"
}

@test "observability otel apply k8s rejects loose token file permissions" {
    make_mock_path
    chmod 644 "${O11Y_TOKEN_FILE}"
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-k8s \
      --realm us0 \
      --cluster-name demo-cluster \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 1 ]
    [[ "$output" == *"is mode 644"* ]] || [[ "$output" == *"is mode 0644"* ]]
    [[ "$output" == *"chmod 600"* ]]
    [ ! -s "${OTEL_CMD_LOG}" ] || ! grep -q "helm upgrade" "${OTEL_CMD_LOG}"
}

@test "observability otel apply k8s never bypasses loose token permissions" {
    make_mock_path
    chmod 644 "${O11Y_TOKEN_FILE}"
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-k8s \
      --realm us0 \
      --cluster-name demo-cluster \
      --platform-hec-url https://splunk.example.com:8088/services/collector/event \
      --enable-logs \
      --platform-hec-token-file "${HEC_TOKEN_FILE}" \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --allow-loose-token-perms \
      --output-dir "${output_dir}"
    [ "$status" -ne 0 ]
    run ! grep -q "helm upgrade --install" "${OTEL_CMD_LOG}"
}

@test "observability otel apply k8s surfaces helm failure exit code" {
    make_mock_path
    # Override helm to fail only on `upgrade --install`; let `repo add` and
    # `repo update` succeed so the failure surfaces from the actual chart
    # install step (the operator-impacting case).
    cat > "${TMP_ROOT}/bin/helm" <<'SH'
#!/usr/bin/env bash
printf 'helm %s\n' "$*" >> "${OTEL_CMD_LOG}"
if [[ "${1:-}" == "upgrade" ]]; then
  echo "helm: pretend the chart values are invalid" >&2
  exit 7
fi
if [[ "${1:-}" == "version" ]]; then
  printf 'v4.2.2\n'
fi
if [[ "${1:-}" == "list" ]]; then
  printf '[]\n'
fi
if [[ "${1:-}" == "template" ]]; then
  cat <<'YAML'
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: splunk-otel-collector-agent
spec:
  template:
    spec:
      containers:
      - name: otel-collector
        image: quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: splunk-otel-collector-k8s-cluster-receiver
spec:
  template:
    spec:
      containers:
      - name: otel-collector
        image: quay.io/signalfx/splunk-otel-collector@sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410
---
apiVersion: v1
kind: Pod
metadata:
  name: mock-validate-secret
spec:
  containers:
  - name: validate-secret
    image: registry.access.redhat.com/ubi9/ubi@sha256:8bf0e8f20737e9c8a68c8a498299e9504ab397b1b1f2837acb2fef12ec698f0e
YAML
fi
exit 0
SH
    chmod +x "${TMP_ROOT}/bin/helm"
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-k8s \
      --realm us0 \
      --cluster-name demo-cluster \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -ne 0 ]
    grep -q "helm upgrade --install" "${OTEL_CMD_LOG}"
}
