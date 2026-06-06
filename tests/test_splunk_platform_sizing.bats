#!/usr/bin/env bats
# Tests for the Splunk platform sizing shell entrypoint.

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    TMP_ROOT="$(mktemp -d)"
    SIZE="${PROJECT_ROOT}/skills/splunk-platform-sizing/scripts/size.sh"
}

teardown() {
    rm -rf "${TMP_ROOT}"
}

@test "size.sh --help exits zero and shows usage" {
    run bash "${SIZE}" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Platform Sizing" ]]
    [[ "$output" =~ "--daily-ingest-gb" ]]
}

@test "size.sh requires --daily-ingest-gb" {
    run bash "${SIZE}" --retention-days 30
    [ "$status" -ne 0 ]
    [[ "$output" =~ "--daily-ingest-gb is required" ]]
}

@test "size.sh rejects unknown option" {
    run bash "${SIZE}" --daily-ingest-gb 100 --bogus
    [ "$status" -ne 0 ]
    [[ "$output" =~ "Unknown option: --bogus" ]]
}

@test "size.sh dry-run writes no files" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${SIZE}" --daily-ingest-gb 80 --output-dir "${output_dir}" --dry-run
    [ "$status" -eq 0 ]
    [ ! -e "${output_dir}" ]
}

@test "size.sh render writes report and json" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${SIZE}" --daily-ingest-gb 500 --workload-profile es --ha \
      --output-dir "${output_dir}"
    [ "$status" -eq 0 ]
    [ -f "${output_dir}/sizing-report.md" ]
    [ -f "${output_dir}/sizing.json" ]
}

@test "size.sh standalone gate fails for large ingest" {
    output_dir="${TMP_ROOT}/rendered"
    run bash "${SIZE}" --daily-ingest-gb 500 --deployment-target standalone \
      --output-dir "${output_dir}"
    [ "$status" -eq 2 ]
    [[ "$output" =~ "not viable" ]]
}
