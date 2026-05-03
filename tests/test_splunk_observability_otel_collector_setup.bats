#!/usr/bin/env bats
# Tests for Splunk Observability OTel Collector setup shell entrypoints.

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

if [[ "${cmd_name}" == "kubectl" && "${1:-}" == "create" ]]; then
  printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: mock\n'
fi

if [[ "${cmd_name}" == "curl" ]]; then
  out=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -o) out="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  if [[ -n "${out}" ]]; then
    cat > "${out}" <<'INSTALLER'
#!/usr/bin/env sh
printf 'installer %s\n' "$*" >> "${OTEL_CMD_LOG}"
cat >/dev/null
INSTALLER
    chmod +x "${out}"
  fi
fi

if [[ "${cmd_name}" == "sudo" ]]; then
  exec "$@"
fi

if [[ "${cmd_name}" == "ssh" ]]; then
  cat >> "${OTEL_CMD_LOG}"
fi

exit 0
SH
    chmod +x "${TMP_ROOT}/bin/${name}"
}

make_mock_path() {
    mkdir -p "${TMP_ROOT}/bin"
    export OTEL_CMD_LOG="${TMP_ROOT}/commands.log"
    : > "${OTEL_CMD_LOG}"
    for cmd in kubectl helm aws curl sudo scp ssh; do
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
      --platform-hec-url https://splunk.example.com:8088/services/collector \
      --platform-hec-token-file "${HEC_TOKEN_FILE}" \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/k8s/values.yaml" ]
    [ -f "${output_dir}/linux/install-local.sh" ]
    [ ! -s "${OTEL_CMD_LOG}" ]
    ! grep -R "O11Y_SECRET_SHOULD_NOT_LEAK\\|HEC_SECRET_SHOULD_NOT_LEAK" "${output_dir}"
}

@test "observability otel renders platform hec helper without running hec setup" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --render-k8s \
      --render-platform-hec-helper \
      --realm us0 \
      --cluster-name demo-cluster \
      --platform-hec-url https://splunk.example.com:8088/services/collector \
      --hec-platform cloud \
      --hec-token-name splunk_otel_k8s_logs \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/platform-hec/render-hec-service.sh" ]
    [ -f "${output_dir}/platform-hec/apply-hec-service.sh" ]
    grep -q "splunk-hec-service-setup/scripts/setup.sh" "${output_dir}/platform-hec/apply-hec-service.sh"
    grep -q -- "--write-token-file" "${output_dir}/platform-hec/apply-hec-service.sh"
    grep -q "platform-hec/.splunk_platform_hec_token" "${output_dir}/k8s/create-secret.sh"
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
      --platform-hec-url https://splunk.example.com:8088/services/collector \
      --platform-hec-token-file "${HEC_TOKEN_FILE}" \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    grep -q "kubectl create secret generic" "${OTEL_CMD_LOG}"
    grep -q "helm upgrade --install" "${OTEL_CMD_LOG}"
    ! grep -q "O11Y_SECRET_SHOULD_NOT_LEAK\\|HEC_SECRET_SHOULD_NOT_LEAK" "${OTEL_CMD_LOG}"
}

@test "observability otel apply linux local feeds token through stdin path" {
    make_mock_path
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-linux \
      --realm us0 \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    grep -q "curl -fsSL" "${OTEL_CMD_LOG}"
    grep -q "installer --realm us0" "${OTEL_CMD_LOG}"
    ! grep -q "O11Y_SECRET_SHOULD_NOT_LEAK" "${OTEL_CMD_LOG}"
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
    grep -q "ssh -p 22 ec2-user@otel.example.com bash -s" "${OTEL_CMD_LOG}"
    grep -q "VERIFY_ACCESS_TOKEN=false" "${OTEL_CMD_LOG}"
    ! grep -q "O11Y_SECRET_SHOULD_NOT_LEAK" "${OTEL_CMD_LOG}"
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

@test "observability otel apply k8s allows loose perms with --allow-loose-token-perms" {
    make_mock_path
    chmod 644 "${O11Y_TOKEN_FILE}"
    output_dir="${TMP_ROOT}/rendered"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \
      --apply-k8s \
      --realm us0 \
      --cluster-name demo-cluster \
      --o11y-token-file "${O11Y_TOKEN_FILE}" \
      --allow-loose-token-perms \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    grep -q "helm upgrade --install" "${OTEL_CMD_LOG}"
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
