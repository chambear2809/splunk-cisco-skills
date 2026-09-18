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
        echo '{"name":"myindex","datatype": "metric"}'
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
        echo '{"name":"myindex","dataType": "event"}'
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
        echo '{"name":"myindex","spec": {"datatype": "metric"}}'
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
        echo '{"index": {"name":"myindex","datatype": "metric"}}'
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
        echo '[{"type":"http","response":"{\"name\":\"myindex\",\"datatype\":\"metric\"}"}]'
    }
    export -f acs_prepare_context acs_command

    run cloud_get_index_datatype "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "cloud index observation rejects empty malformed and wrong-identity describe success" {
    source "${LIB_DIR}/acs_helpers.sh"
    acs_prepare_context() { return 0; }
    acs_command() { printf '%s' "${ACS_INDEX_BODY}"; }
    export -f acs_prepare_context acs_command

    for ACS_INDEX_BODY in '' 'not-json' '{}' '{"datatype":"event"}' '{"name":"another-index","datatype":"event"}'; do
        export ACS_INDEX_BODY
        run cloud_check_index "myindex"
        [ "$status" -ne 0 ]
        run cloud_get_index_datatype "myindex"
        [ "$status" -ne 0 ]
    done
}

# ---------------------------------------------------------------------------
# rest_get_index_datatype
# ---------------------------------------------------------------------------

@test "rest_get_index_datatype extracts datatype from REST API response" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        shift  # skip session key
        printf '%s\n%s' \
            '{"entry": [{"name":"myindex","content": {"datatype": "metric"}}]}' \
            '200'
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
        printf '%s\n%s' \
            '{"entry": [{"name":"myindex","content": {"datatype": "event"}}]}' \
            '200'
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
        printf '%s\n%s' \
            '{"entry": [{"name":"myindex","content": {}}]}' \
            '200'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "event" ]
}

@test "rest_get_index_datatype rejects an empty entry observation" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        shift
        printf '%s\n%s' '{"entry": []}' '200'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -ne 0 ]
}

@test "rest_get_index_datatype rejects a non-2xx exact-entry body" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        printf '%s\n%s' \
            '{"entry":[{"name":"myindex","content":{"datatype":"metric"}}]}' \
            '503'
    }
    export -f splunk_curl

    run rest_get_index_datatype "fake-session-key" "https://localhost:8089" "myindex"
    [ "$status" -ne 0 ]
    [ -z "$output" ]
}

@test "rest_create_index refuses mutation when the absence probe fails" {
    source "${LIB_DIR}/rest_helpers.sh"
    marker="${BATS_TMPDIR}/rest-index-create-refused-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export REST_INDEX_CREATE_MARKER="${marker}"
    splunk_curl() { return 1; }
    splunk_curl_post() { touch "${REST_INDEX_CREATE_MARKER}"; }
    export -f splunk_curl splunk_curl_post

    run rest_create_index "session-key" "https://splunk.example:8089" "myindex" "512000" "event"

    [ "$status" -ne 0 ]
    [ ! -e "${marker}" ]
    [[ "$output" == *"absence was not verified"* ]]
}

@test "rest_create_index verifies exact state after a conflict response" {
    source "${LIB_DIR}/rest_helpers.sh"
    marker="${BATS_TMPDIR}/rest-index-create-conflict-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export REST_INDEX_CREATE_MARKER="${marker}"
    splunk_curl() {
        if [[ -e "${REST_INDEX_CREATE_MARKER}" ]]; then
            if [[ " $* " == *" -w "* ]]; then
                printf '%s\n%s' '{"entry":[{"name":"myindex","content":{"datatype":"metric"}}]}' '200'
            else
                printf '%s' '{"entry":[{"name":"myindex","content":{"datatype":"metric"}}]}'
            fi
        else
            printf '%s\n%s' '{}' '404'
        fi
    }
    splunk_curl_post() {
        touch "${REST_INDEX_CREATE_MARKER}"
        printf '\n409'
    }
    export -f splunk_curl splunk_curl_post

    run rest_create_index "session-key" "https://splunk.example:8089" "myindex" "512000" "metric"

    [ "$status" -eq 0 ]
    [ -e "${marker}" ]
}

# ---------------------------------------------------------------------------
# platform_get_index_datatype
# ---------------------------------------------------------------------------

@test "platform_get_index_datatype dispatches to cloud_get_index_datatype on cloud" {
    source "${LIB_DIR}/acs_helpers.sh"

    # Force cloud platform through the production selector surface.
    resolve_splunk_platform() { printf '%s\n' "cloud"; }
    cloud_get_index_datatype() {
        echo "metric"
    }
    export -f resolve_splunk_platform cloud_get_index_datatype

    run platform_get_index_datatype "sk" "https://uri" "myindex"
    [ "$status" -eq 0 ]
    [ "$output" = "metric" ]
}

@test "platform_get_index_datatype dispatches to rest_get_index_datatype on enterprise" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"

    # Force enterprise platform through the production selector surface.
    resolve_splunk_platform() { printf '%s\n' "enterprise"; }
    rest_get_index_datatype() {
        echo "event"
    }
    export -f resolve_splunk_platform rest_get_index_datatype

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
    export ACS_DESCRIBE_MARKER="${BATS_TMPDIR}/acs_describe_seen_$$"
    TEST_TEMP_FILES+=("${ACS_DESCRIBE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            if [[ -e "${ACS_DESCRIBE_MARKER}" ]]; then
                printf '%s' '{"name":"myindex","datatype":"metric"}'
                return 0
            fi
            touch "${ACS_DESCRIBE_MARKER}"
            printf '%s' '{"statusCode":404}' >&2
            return 1
        fi
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

    export ACS_DESCRIBE_MARKER="${BATS_TMPDIR}/acs_describe_seen_default_$$"
    TEST_TEMP_FILES+=("${ACS_DESCRIBE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            if [[ -e "${ACS_DESCRIBE_MARKER}" ]]; then
                printf '%s' '{"name":"myindex"}'
                return 0
            fi
            touch "${ACS_DESCRIBE_MARKER}"
            printf '%s' 'index myindex not found' >&2
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

@test "cloud_create_index refuses mutation when describe failure does not prove absence" {
    source "${LIB_DIR}/acs_helpers.sh"

    export ACS_CREATE_MARKER="${BATS_TMPDIR}/acs_create_refused_$$"
    TEST_TEMP_FILES+=("${ACS_CREATE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            printf '%s' '{"statusCode":500}' >&2
            return 1
        fi
        touch "${ACS_CREATE_MARKER}"
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "event"
    [ "$status" -ne 0 ]
    [ ! -e "${ACS_CREATE_MARKER}" ]
    [[ "$output" == *"absence was not verified"* ]]
}

@test "cloud_create_index reports incomplete when post-create describe fails" {
    source "${LIB_DIR}/acs_helpers.sh"

    export ACS_CREATE_MARKER="${BATS_TMPDIR}/acs_create_postread_$$"
    TEST_TEMP_FILES+=("${ACS_CREATE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            if [[ ! -e "${ACS_CREATE_MARKER}" ]]; then
                printf '%s' '{"statusCode":404}' >&2
            else
                printf '%s' '{"statusCode":503}' >&2
            fi
            return 1
        fi
        touch "${ACS_CREATE_MARKER}"
        return 0
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "event"
    [ "$status" -ne 0 ]
    [ -e "${ACS_CREATE_MARKER}" ]
    [[ "$output" == *"post-create readback failed"* ]]
}

@test "cloud_create_index skips creation when index already exists" {
    source "${LIB_DIR}/acs_helpers.sh"

    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            printf '%s' '{"name":"myindex","datatype":"metric"}'
            return 0
        fi
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "metric"
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "cloud_create_index refuses creation after a successful but empty describe" {
    source "${LIB_DIR}/acs_helpers.sh"

    export ACS_CREATE_MARKER="${BATS_TMPDIR}/acs_create_empty_describe_$$"
    TEST_TEMP_FILES+=("${ACS_CREATE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            return 0
        fi
        touch "${ACS_CREATE_MARKER}"
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "event"
    [ "$status" -ne 0 ]
    [ ! -e "${ACS_CREATE_MARKER}" ]
    [[ "$output" == *"without an exact index observation"* ]]
}

@test "cloud_create_index rejects a non-success structured describe wrapper" {
    source "${LIB_DIR}/acs_helpers.sh"

    export ACS_CREATE_MARKER="${BATS_TMPDIR}/acs_create_non_success_wrapper_$$"
    TEST_TEMP_FILES+=("${ACS_CREATE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            printf '%s' '[{"type":"http","statusCode":500,"response":"{\"name\":\"myindex\",\"datatype\":\"event\"}"}]'
            return 0
        fi
        touch "${ACS_CREATE_MARKER}"
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "event"
    [ "$status" -ne 0 ]
    [ ! -e "${ACS_CREATE_MARKER}" ]
}

@test "cloud_create_index rejects ambiguous structured absence evidence" {
    source "${LIB_DIR}/acs_helpers.sh"

    export ACS_CREATE_MARKER="${BATS_TMPDIR}/acs_create_ambiguous_absence_$$"
    TEST_TEMP_FILES+=("${ACS_CREATE_MARKER}")
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "indexes" && "$2" == "describe" ]]; then
            printf '%s' '[{"type":"http","statusCode":404},{"type":"http","statusCode":500}]' >&2
            return 1
        fi
        touch "${ACS_CREATE_MARKER}"
    }
    export -f acs_prepare_context acs_command

    run cloud_create_index "myindex" "90" "event"
    [ "$status" -ne 0 ]
    [ ! -e "${ACS_CREATE_MARKER}" ]
    [[ "$output" == *"absence was not verified"* ]]
}

# ---------------------------------------------------------------------------
# platform_create_index -- passes index_type through
# ---------------------------------------------------------------------------

@test "platform_create_index passes index_type to cloud_create_index on cloud" {
    source "${LIB_DIR}/acs_helpers.sh"

    resolve_splunk_platform() { printf '%s\n' "cloud"; }
    cloud_create_index() {
        # $1=idx, $2=searchable_days, $3=index_type
        echo "cloud_create_index $1 $2 $3"
    }
    export -f resolve_splunk_platform cloud_create_index

    run platform_create_index "sk" "https://uri" "myindex" "512000" "metric"
    [ "$status" -eq 0 ]
    [[ "$output" == *"cloud_create_index myindex"* ]]
    [[ "$output" == *"metric"* ]]
}

@test "platform_create_index passes index_type to rest_create_index on enterprise" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"

    resolve_splunk_platform() { printf '%s\n' "enterprise"; }
    rest_create_index() {
        # $1=sk, $2=uri, $3=idx, $4=max_size, $5=index_type
        echo "rest_create_index $3 $4 $5"
    }
    export -f resolve_splunk_platform rest_create_index

    run platform_create_index "sk" "https://uri" "myindex" "512000" "metric"
    [ "$status" -eq 0 ]
    [[ "$output" == *"rest_create_index myindex 512000 metric"* ]]
}

@test "platform_create_index uses cluster-manager bundle workflow for clustered ingest" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    source "${LIB_DIR}/deployment_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"

    resolve_splunk_platform() { printf '%s\n' "enterprise"; }
    deployment_index_bundle_profile() { echo "cluster-manager"; }
    deployment_create_cluster_bundle_index() {
        echo "bundle_index $1 $2 $3"
    }
    export -f resolve_splunk_platform deployment_index_bundle_profile deployment_create_cluster_bundle_index

    run platform_create_index "sk" "https://uri" "myindex" "512000" "metric"
    [ "$status" -eq 0 ]
    [[ "$output" == *"bundle_index myindex 512000 metric"* ]]
}

@test "platform_create_index defaults index_type to event" {
    source "${LIB_DIR}/acs_helpers.sh"

    resolve_splunk_platform() { printf '%s\n' "cloud"; }
    cloud_create_index() {
        echo "cloud_create_index $1 $2 $3"
    }
    export -f resolve_splunk_platform cloud_create_index

    run platform_create_index "sk" "https://uri" "myindex"
    [ "$status" -eq 0 ]
    [[ "$output" == *"event"* ]]
}
