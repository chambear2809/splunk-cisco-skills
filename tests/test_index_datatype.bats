#!/usr/bin/env bats
# Tests for index datatype helpers and create-index functions.
# Requires bats-core: brew install bats-core

setup() {
    export _CRED_HELPERS_LOADED=""
    export _CREDENTIALS_LOADED=""
    export _REST_HELPERS_LOADED=""
    export _ACS_HELPERS_LOADED=""
    export _SPLUNKBASE_HELPERS_LOADED=""
    export _CONFIGURE_ACCOUNT_HELPERS_LOADED=""
    export _HOST_BOOTSTRAP_HELPERS_LOADED=""
    export _DEPLOYMENT_HELPERS_LOADED=""
    export SPLUNK_USER="testuser"
    export SPLUNK_PASS="testpass"
    export SPLUNK_VERIFY_SSL="false"

    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"

    TEST_TEMP_FILES=()
}

teardown() {
    for f in "${TEST_TEMP_FILES[@]+"${TEST_TEMP_FILES[@]}"}"; do
        rm -rf "${f}"
    done
}

# ---------------------------------------------------------------------------
# cloud_get_index_datatype
# ---------------------------------------------------------------------------

@test "cloud_get_index_datatype extracts datatype from top-level field" {
    source "${LIB_DIR}/acs_helpers.sh"

    # Stub acs_prepare_context and acs_command to return canned JSON
    acs_prepare_context() { return 0; }
    acs_command() {
        echo '{"datatype": "metric"}'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "cloud_get_index_datatype extracts dataType (camelCase) from top-level" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        echo '{"dataType": "event"}'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

@test "cloud_get_index_datatype extracts datatype from nested spec object" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        echo '{"spec": {"datatype": "metric"}}'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "cloud_get_index_datatype extracts datatype from nested index object" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        echo '{"index": {"datatype": "metric"}}'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "cloud_get_index_datatype defaults to event when datatype is missing" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        echo '{"name": "myindex"}'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

@test "cloud_get_index_datatype extracts from ACS structured response" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        echo '[{"type":"http","response":"{\"datatype\":\"metric\"}"}]'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

# ---------------------------------------------------------------------------
# rest_get_index_datatype
# ---------------------------------------------------------------------------

@test "rest_get_index_datatype extracts datatype from REST API response" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        shift  # skip session key
        echo '{"entry": [{"content": {"datatype": "metric"}}]}'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "rest_get_index_datatype returns event when datatype is event" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        shift
        echo '{"entry": [{"content": {"datatype": "event"}}]}'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

@test "rest_get_index_datatype defaults to event when field is empty" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        shift
        echo '{"entry": [{"content": {}}]}'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

@test "rest_get_index_datatype defaults to event when entry is empty" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        shift
        echo '{"entry": []}'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

# ---------------------------------------------------------------------------
# platform_get_index_datatype
# ---------------------------------------------------------------------------

@test "platform_get_index_datatype dispatches to cloud_get_index_datatype on cloud" {
    source "${LIB_DIR}/acs_helpers.sh"

    # Force cloud platform
    is_splunk_cloud() { return 0; }
    cloud_get_index_datatype() {
        echo "metric"
    }
    export -f is_splunk_cloud cloud_get_index_datatype

    run platform_get_index_datatype "sk" "https://uri" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "platform_get_index_datatype dispatches to rest_get_index_datatype on enterprise" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"

    # Force enterprise platform
    is_splunk_cloud() { return 1; }
    rest_get_index_datatype() {
        echo "event"
    }
    export -f is_splunk_cloud rest_get_index_datatype

    run platform_get_index_datatype "sk" "https://uri" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

# ---------------------------------------------------------------------------
# cloud_create_index -- includes --data-type argument
# ---------------------------------------------------------------------------

@test "cloud_create_index passes data-type argument to acs indexes create" {
    source "${LIB_DIR}/acs_helpers.sh"

    local capture_file="${BATS_TMPDIR}/acs_create_args_$$"
    acs_prepare_context() { return 0; }
    acs_command() {
        # First call: indexes describe (should fail to trigger create)
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            return 1
        fi
        # Second call: indexes create -- capture all args
        echo "$*" > "${BATS_TMPDIR}/acs_create_args_${BASHPID}"
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "metric"
    [ "$status" -eq 0 ]
    # Find the capture file (BASHPID varies inside run subshell)
    local captured
    captured=$(cat "${BATS_TMPDIR}"/acs_create_args_* 2>/dev/null)
    rm -f "${BATS_TMPDIR}"/acs_create_args_*
    [[ "$captured" == *"--data-type"* ]]
    [[ "$captured" == *"metric"* ]]
}

@test "cloud_create_index defaults index_type to event" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            return 1
        fi
        echo "$*" > "${BATS_TMPDIR}/acs_create_args_${BASHPID}"
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex"
    [ "$status" -eq 0 ]
    local captured
    captured=$(cat "${BATS_TMPDIR}"/acs_create_args_* 2>/dev/null)
    rm -f "${BATS_TMPDIR}"/acs_create_args_*
    [[ "$captured" == *"--data-type"* ]]
    [[ "$captured" == *"event"* ]]
}

@test "cloud_create_index skips creation when index already exists" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            return 0  # index exists
        fi
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "metric"
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

# ---------------------------------------------------------------------------
# platform_create_index -- passes index_type through
# ---------------------------------------------------------------------------

@test "platform_create_index passes index_type to cloud_create_index on cloud" {
    source "${LIB_DIR}/acs_helpers.sh"

    is_splunk_cloud() { return 0; }
    cloud_create_index() {
        # $1=idx, $2=searchable_days, $3=index_type
        echo "cloud_create_index $1 $2 $3"
    }
    export -f is_splunk_cloud cloud_create_index

    run platform_create_index "sk" "https://uri" "myindex" "512000" "metric"
    [ "$status" -eq 0 ]
    [[ "$output" == *"cloud_create_index myindex"* ]]
    [[ "$output" == *"metric"* ]]
}

@test "platform_create_index passes index_type to rest_create_index on enterprise" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"

    is_splunk_cloud() { return 1; }
    rest_create_index() {
        # $1=sk, $2=uri, $3=idx, $4=max_size, $5=index_type
        echo "rest_create_index $3 $4 $5"
    }
    export -f is_splunk_cloud rest_create_index

    run platform_create_index "sk" "https://uri" "myindex" "512000" "metric"
    [ "$status" -eq 0 ]
    [[ "$output" == *"rest_create_index myindex 512000 metric"* ]]
}

@test "platform_create_index uses cluster-manager bundle workflow for clustered ingest" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    source "${LIB_DIR}/deployment_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"

    is_splunk_cloud() { return 1; }
    deployment_index_bundle_profile() { echo "cluster-manager"; }
    deployment_create_cluster_bundle_index() {
        echo "bundle_index $1 $2 $3"
    }
    export -f is_splunk_cloud deployment_index_bundle_profile deployment_create_cluster_bundle_index

    run platform_create_index "sk" "https://uri" "myindex" "512000" "metric"
    [ "$status" -eq 0 ]
    [[ "$output" == *"bundle_index myindex 512000 metric"* ]]
}

@test "platform_create_index defaults index_type to event" {
    source "${LIB_DIR}/acs_helpers.sh"

    is_splunk_cloud() { return 0; }
    cloud_create_index() {
        echo "cloud_create_index $1 $2 $3"
    }
    export -f is_splunk_cloud cloud_create_index

    run platform_create_index "sk" "https://uri" "myindex"
    [ "$status" -eq 0 ]
    [[ "$output" == *"event"* ]]
}
