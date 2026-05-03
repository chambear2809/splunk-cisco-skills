#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-federated-search-rendered"
OUTPUT_DIR=""
JSON_OUTPUT=false
LIVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Federated Search Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --output-dir PATH
  --live                    Additionally run status.sh (REST GET /services/data/federated/*).
  --json                    JSON output for CI consumption.
  --help

Validates that:
- All required rendered files exist (README.md, metadata.json, federated.conf.template,
  indexes.conf, server.conf, preflight.sh, apply-search-head.sh, apply-shc-deployer.sh,
  apply-rest.sh, status.sh, global-enable.sh, global-disable.sh).
- federated.conf.template has at least one provider stanza OR a clear "no FSS2S
  providers" comment.
- federated.conf.template contains a per-provider password placeholder
  (__FEDERATED_PASSWORD_FILE_BASE64__*) for every provider stanza so apply
  scripts cannot accidentally ship plaintext passwords.
- aws-s3-providers/<name>.json files are valid JSON and include the required
  FSS3 keys (aws_account_id, aws_region, database, data_catalog,
  aws_glue_tables_allowlist, aws_s3_paths_allowlist).
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

json_array() {
    python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]), end="")
PY
}

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

render_dir="${OUTPUT_DIR}/federated-search"
required=(
    README.md
    metadata.json
    federated.conf.template
    indexes.conf
    server.conf
    preflight.sh
    apply-search-head.sh
    apply-shc-deployer.sh
    apply-rest.sh
    status.sh
    global-enable.sh
    global-disable.sh
)
missing=()
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || missing+=("${file}")
done

ok=true
(( ${#missing[@]} == 0 )) || ok=false

# Inspect federated.conf.template for password-placeholder coverage. Every
# [provider://X] stanza MUST be paired with a per-provider placeholder so the
# apply scripts substitute the password from --password-file. This catches
# rendering bugs that would otherwise ship plaintext passwords on disk.
if [[ -f "${render_dir}/federated.conf.template" ]]; then
    if ! python3 - "${render_dir}/federated.conf.template" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
provider_stanzas = re.findall(r"\[provider://([A-Za-z0-9_-]+)\]", text)
if not provider_stanzas:
    # Either no FSS2S providers were declared (FSS3-only spec) or this is
    # the "no providers" placeholder file. Both are valid.
    sys.exit(0)
for name in provider_stanzas:
    expected = f"__FEDERATED_PASSWORD_FILE_BASE64__{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').upper() or 'PROVIDER'}__"
    if expected not in text:
        sys.exit(f"missing placeholder for provider {name}: {expected}")
PY
    then
        missing+=("federated.conf.template per-provider password placeholder")
        ok=false
    fi
fi

# Inspect any rendered FSS3 payloads for required keys.
if [[ -d "${render_dir}/aws-s3-providers" ]]; then
    for payload in "${render_dir}"/aws-s3-providers/*.json; do
        [[ -f "${payload}" ]] || continue
        if ! python3 - "${payload}" <<'PY'
import json
import sys
from pathlib import Path

required = {"name", "type", "aws_account_id", "aws_region", "database", "data_catalog", "aws_glue_tables_allowlist", "aws_s3_paths_allowlist"}
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
missing = sorted(required - set(data))
if missing:
    sys.exit(f"missing FSS3 keys: {missing}")
if data.get("type") != "aws_s3":
    sys.exit("FSS3 payload type must be 'aws_s3'")
PY
        then
            missing+=("aws-s3-providers/$(basename "${payload}") schema check")
            ok=false
        fi
    done
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    printf '{"target":"federated-search","render_dir":"%s","ok":%s,"missing":%s}\n' "${render_dir}" "${ok}" "$(json_array "${missing[@]}")"
else
    if [[ "${ok}" == "true" ]]; then
        log "Rendered Federated Search assets are present and valid under ${render_dir}."
    else
        log "ERROR: Missing or invalid Federated Search assets under ${render_dir}: ${missing[*]}"
    fi
fi

[[ "${ok}" == "true" ]] || exit 1

if [[ "${LIVE}" == "true" ]]; then
    (cd "${render_dir}" && ./status.sh)
fi
