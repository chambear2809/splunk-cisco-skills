#!/usr/bin/env bats
# Tests for skills/shared/lib/k8s_apply_helpers.sh and the four skills that
# now expose --apply behind --accept-k8s-apply:
#   - splunk-observability-cisco-intersight-integration
#   - splunk-observability-nvidia-gpu-integration
#   - splunk-observability-cisco-nexus-integration
#   - splunk-observability-isovalent-integration
#
# These tests do not contact a real cluster. They verify gate semantics
# (refusal without --accept-k8s-apply) and that --render alone never invokes
# kubectl/helm.

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"

    OUT_DIR="$(mktemp -d)"

    # Stub kubectl and helm to record invocations rather than actually run.
    STUB_BIN="$(mktemp -d)"
    cat > "${STUB_BIN}/kubectl" <<'EOF'
#!/usr/bin/env bash
echo "kubectl $*" >> "${STUB_LOG:-/dev/null}"
exit 0
EOF
    cat > "${STUB_BIN}/helm" <<'EOF'
#!/usr/bin/env bash
echo "helm $*" >> "${STUB_LOG:-/dev/null}"
exit 0
EOF
    chmod +x "${STUB_BIN}/kubectl" "${STUB_BIN}/helm"

    STUB_LOG="${OUT_DIR}/calls.log"
    : > "${STUB_LOG}"
    export STUB_LOG
}

teardown() {
    rm -rf "${OUT_DIR}" "${STUB_BIN}"
}

# --- shared lib direct unit tests -----------------------------------------

@test "k8s_apply_helpers: require_apply_acceptance refuses without flag" {
    run bash -c "
        source ${PROJECT_ROOT}/skills/shared/lib/k8s_apply_helpers.sh
        require_apply_acceptance
    "
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --accept-k8s-apply"* ]]
}

@test "k8s_apply_helpers: require_apply_acceptance passes when flag set" {
    run bash -c "
        source ${PROJECT_ROOT}/skills/shared/lib/k8s_apply_helpers.sh
        K8S_APPLY_ACCEPTED=true
        require_apply_acceptance
    "
    [ "$status" -eq 0 ]
}

@test "k8s_apply_helpers: parse_k8s_apply_flag recognizes accept + dry-run" {
    run bash -c "
        source ${PROJECT_ROOT}/skills/shared/lib/k8s_apply_helpers.sh
        parse_k8s_apply_flag --accept-k8s-apply && parse_k8s_apply_flag --dry-run \
            && [[ \"\${K8S_APPLY_ACCEPTED}\" == 'true' ]] \
            && [[ \"\${K8S_APPLY_DRY_RUN}\" == 'true' ]]
    "
    [ "$status" -eq 0 ]
}

@test "k8s_apply_helpers: require_kubectl fails when kubectl missing" {
    run bash -c "
        PATH=/nope source ${PROJECT_ROOT}/skills/shared/lib/k8s_apply_helpers.sh
        PATH=/nope require_kubectl
    "
    [ "$status" -ne 0 ]
    [[ "$output" == *"kubectl not found"* ]]
}

# --- intersight gate ------------------------------------------------------

@test "intersight: --apply without --accept-k8s-apply refuses" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-cisco-intersight-integration/scripts/setup.sh" \
        --apply \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --accept-k8s-apply"* ]]
}

@test "intersight: --render alone never invokes kubectl or helm" {
    PATH="${STUB_BIN}:${PATH}" run bash "${PROJECT_ROOT}/skills/splunk-observability-cisco-intersight-integration/scripts/setup.sh" \
        --render \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    [ "$status" -eq 0 ]
    [ ! -s "${STUB_LOG}" ]
    [ -x "${OUT_DIR}/scripts/apply-intersight-manifests.sh" ]
}

# --- nvidia gpu gate ------------------------------------------------------

@test "nvidia-gpu: --apply-pod-labels-patch without --accept-k8s-apply refuses" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh" \
        --enable-dcgm-pod-labels --apply-pod-labels-patch \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --accept-k8s-apply"* ]]
}

@test "nvidia-gpu: --apply-pod-labels-patch without --enable-dcgm-pod-labels refuses" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh" \
        --apply-pod-labels-patch --accept-k8s-apply \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --enable-dcgm-pod-labels"* ]]
}

# --- nexus gate -----------------------------------------------------------

@test "nexus: --apply without --accept-k8s-apply refuses" {
    fake_token="$(mktemp)"
    chmod 600 "${fake_token}"
    echo "fake" > "${fake_token}"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh" \
        --apply \
        --o11y-token-file "${fake_token}" \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes \
        --nexus-device "leaf1:10.0.0.1:22"
    rm -f "${fake_token}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --accept-k8s-apply"* ]]
}

@test "nexus: --apply with --accept-k8s-apply but no token file refuses" {
    empty_creds="$(mktemp)"
    run env -u SPLUNK_O11Y_TOKEN_FILE SPLUNK_CREDENTIALS_FILE="${empty_creds}" bash \
        "${PROJECT_ROOT}/skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh" \
        --apply --accept-k8s-apply \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes \
        --nexus-device "leaf1:10.0.0.1:22"
    rm -f "${empty_creds}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"o11y-token-file"* ]] || [[ "$output" == *"O11Y_TOKEN_FILE"* ]]
}

# --- isovalent gate -------------------------------------------------------

@test "isovalent: --apply without --accept-k8s-apply refuses" {
    fake_token="$(mktemp)"
    chmod 600 "${fake_token}"
    echo "fake" > "${fake_token}"
    run bash "${PROJECT_ROOT}/skills/splunk-observability-isovalent-integration/scripts/setup.sh" \
        --apply \
        --o11y-token-file "${fake_token}" \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    rm -f "${fake_token}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --accept-k8s-apply"* ]]
}

@test "isovalent: --render alone produces apply helper script" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-isovalent-integration/scripts/setup.sh" \
        --render \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    [ "$status" -eq 0 ]
    [ -x "${OUT_DIR}/scripts/apply-isovalent-overlay.sh" ]
}

# --- dbmon gate -----------------------------------------------------------

@test "dbmon: --render produces apply-dbmon-overlay.sh" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-database-monitoring-setup/scripts/setup.sh" \
        --render \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    [ "$status" -eq 0 ]
    [ -x "${OUT_DIR}/scripts/apply-dbmon-overlay.sh" ]
}

@test "dbmon: --apply without --accept-k8s-apply refuses" {
    bash "${PROJECT_ROOT}/skills/splunk-observability-database-monitoring-setup/scripts/setup.sh" \
        --render --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes >/dev/null

    fake_token="$(mktemp)"
    chmod 600 "${fake_token}"
    echo "fake" > "${fake_token}"
    run env SPLUNK_O11Y_TOKEN_FILE="${fake_token}" bash \
        "${PROJECT_ROOT}/skills/splunk-observability-database-monitoring-setup/scripts/setup.sh" \
        --apply \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    rm -f "${fake_token}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"requires --accept-k8s-apply"* ]]
}

@test "dbmon: --apply with --accept-k8s-apply but no token file refuses" {
    bash "${PROJECT_ROOT}/skills/splunk-observability-database-monitoring-setup/scripts/setup.sh" \
        --render --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes >/dev/null

    empty_creds="$(mktemp)"
    run env -u SPLUNK_O11Y_TOKEN_FILE SPLUNK_CREDENTIALS_FILE="${empty_creds}" bash \
        "${PROJECT_ROOT}/skills/splunk-observability-database-monitoring-setup/scripts/setup.sh" \
        --apply --accept-k8s-apply \
        --output-dir "${OUT_DIR}" \
        --realm us0 --cluster-name t --distribution kubernetes
    rm -f "${empty_creds}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"SPLUNK_O11Y_TOKEN_FILE"* ]]
}
