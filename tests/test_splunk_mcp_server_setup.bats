#!/usr/bin/env bats

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
}

@test "splunk-mcp-server setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk MCP Server Setup" ]]
    [[ "$output" =~ "--uninstall" ]]
    [[ "$output" =~ "--cursor-workspace" ]]
    [[ "$output" =~ "--no-register-codex" ]]
    [[ "$output" =~ "--no-configure-cursor" ]]
}

@test "splunk-mcp-server validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk MCP Server Validation" ]]
}

@test "splunk-mcp-server setup renders bundle and auto-applies Codex and Cursor config" {
    work_dir="$(mktemp -d)"
    home_dir="${work_dir}/home"
    token_file="${work_dir}/splunk.token"
    output_dir="${work_dir}/rendered"
    workspace_dir="${work_dir}/cursor-workspace"

    mkdir -p "${home_dir}" "${workspace_dir}"
    printf '%s' 'encrypted-token-value' > "${token_file}"
    chmod 600 "${token_file}"

    run env HOME="${home_dir}" bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" \
      --render-clients \
      --mcp-url "https://splunk.example.invalid:8089/services/mcp" \
      --bearer-token-file "${token_file}" \
      --output-dir "${output_dir}" \
      --client-name "splunk-shared" \
      --cursor-workspace "${workspace_dir}"

    [ "$status" -eq 0 ]
    [ -f "${output_dir}/.cursor/mcp.json" ]
    [ -f "${output_dir}/run-splunk-mcp.sh" ]
    [ -f "${output_dir}/register-codex-mcp.sh" ]
    [ -f "${output_dir}/.env.splunk-mcp" ]
    [ -f "${workspace_dir}/.cursor/mcp.json" ]

    run cat "${output_dir}/.cursor/mcp.json"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "\"splunk-shared\"" ]]
    [[ "$output" =~ "\"type\": \"stdio\"" ]]
    [[ "$output" =~ "\\\$\\{workspaceFolder\\}/run-splunk-mcp.sh" ]]

    run cat "${workspace_dir}/.cursor/mcp.json"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "\"splunk-shared\"" ]]
    [[ "$output" =~ "\"type\": \"stdio\"" ]]
    [[ "$output" == *"${output_dir}/run-splunk-mcp.sh"* ]]

    run cat "${output_dir}/register-codex-mcp.sh"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "codex mcp add" ]]
    [[ "$output" =~ "run-splunk-mcp.sh" ]]

    run env HOME="${home_dir}" codex mcp get "splunk-shared" --json
    [ "$status" -eq 0 ]
    [[ "$output" =~ "\"name\":\"splunk-shared\"" || "$output" =~ "\"name\": \"splunk-shared\"" ]]
    [[ "$output" == *"${output_dir}/run-splunk-mcp.sh"* ]]

    rm -rf "${work_dir}"
}

@test "splunk-mcp-server setup can skip Codex registration" {
    work_dir="$(mktemp -d)"
    home_dir="${work_dir}/home"
    token_file="${work_dir}/splunk.token"
    output_dir="${work_dir}/rendered"
    workspace_dir="${work_dir}/cursor-workspace"

    mkdir -p "${home_dir}" "${workspace_dir}"
    printf '%s' 'encrypted-token-value' > "${token_file}"
    chmod 600 "${token_file}"

    run env HOME="${home_dir}" bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" \
      --render-clients \
      --mcp-url "https://splunk.example.invalid:8089/services/mcp" \
      --bearer-token-file "${token_file}" \
      --output-dir "${output_dir}" \
      --cursor-workspace "${workspace_dir}" \
      --client-name "splunk-no-codex" \
      --no-register-codex

    [ "$status" -eq 0 ]
    [ -f "${workspace_dir}/.cursor/mcp.json" ]

    run env HOME="${home_dir}" codex mcp get "splunk-no-codex" --json
    [ "$status" -ne 0 ]

    rm -rf "${work_dir}"
}

@test "splunk-mcp-server setup can skip Cursor workspace updates" {
    work_dir="$(mktemp -d)"
    home_dir="${work_dir}/home"
    token_file="${work_dir}/splunk.token"
    output_dir="${work_dir}/rendered"
    workspace_dir="${work_dir}/cursor-workspace"

    mkdir -p "${home_dir}" "${workspace_dir}"
    printf '%s' 'encrypted-token-value' > "${token_file}"
    chmod 600 "${token_file}"

    run env HOME="${home_dir}" bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" \
      --render-clients \
      --mcp-url "https://splunk.example.invalid:8089/services/mcp" \
      --bearer-token-file "${token_file}" \
      --output-dir "${output_dir}" \
      --cursor-workspace "${workspace_dir}" \
      --client-name "splunk-no-cursor" \
      --no-configure-cursor

    [ "$status" -eq 0 ]
    [ ! -f "${workspace_dir}/.cursor/mcp.json" ]

    run env HOME="${home_dir}" codex mcp get "splunk-no-cursor" --json
    [ "$status" -eq 0 ]
    [[ "$output" =~ "\"name\":\"splunk-no-cursor\"" || "$output" =~ "\"name\": \"splunk-no-cursor\"" ]]

    rm -rf "${work_dir}"
}

@test "splunk-mcp-server setup rejects token minting when encrypted tokens are disabled in the same run" {
    run bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" \
      --require-encrypted-token false \
      --write-token-file /tmp/splunk_mcp.token \
      --token-user admin

    [ "$status" -eq 1 ]
    [[ "$output" =~ "require_encrypted_token=true" ]]
}

@test "splunk-mcp-server setup rejects install and uninstall in the same run" {
    run bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" \
      --install \
      --uninstall

    [ "$status" -eq 1 ]
    [[ "$output" =~ "--install and --uninstall cannot be used together" ]]
}

@test "splunk-mcp-server setup rejects uninstall mixed with other flags" {
    run bash "${PROJECT_ROOT}/skills/splunk-mcp-server-setup/scripts/setup.sh" \
      --uninstall \
      --render-clients

    [ "$status" -eq 1 ]
    [[ "$output" =~ "--uninstall must be run by itself" ]]
}
