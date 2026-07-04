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
  apply-rest.sh, status.sh, global-enable.sh, global-disable.sh,
  data-management-federation-handoff.md, specialized-federation-handoff.md,
  legacy-fss3-migration.md).
- federated.conf.template has at least one provider stanza OR a clear "no FSS2S
  providers" comment.
- federated.conf.template contains a per-provider password placeholder
  (__FEDERATED_PASSWORD_FILE_BASE64__*) for every provider stanza so apply
  scripts cannot accidentally ship plaintext passwords.
- aws-s3-providers/<name>.json inventory records are valid JSON and include the
  required FSS3 keys (aws_account_id, aws_region, database, data_catalog,
  aws_glue_tables_allowlist, aws_s3_paths_allowlist), while lifecycle metadata
  and apply scripts preserve the migration-evidence-only boundary.
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
    data-management-federation-handoff.md
    specialized-federation-handoff.md
    legacy-fss3-migration.md
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

# The lifecycle metadata is part of the product-safety contract. Keep Amazon
# Security Lake and Cisco SAL distinct from generic aws_s3, retain current S3
# catalog choices, and mark legacy FSS3 as a migration path.
if [[ -f "${render_dir}/metadata.json" && -f "${render_dir}/specialized-federation-handoff.md" && -f "${render_dir}/legacy-fss3-migration.md" ]]; then
    if ! python3 - \
        "${render_dir}/metadata.json" \
        "${render_dir}/specialized-federation-handoff.md" \
        "${render_dir}/legacy-fss3-migration.md" <<'PY'
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
specialized_text = Path(sys.argv[2]).read_text(encoding="utf-8")
legacy_text = Path(sys.argv[3]).read_text(encoding="utf-8")

specialized = {
    item.get("provider_type"): item
    for item in metadata.get("specialized_federation_handoffs", [])
}
if set(specialized) != {"aws_lake", "aws_s3_sal"}:
    raise SystemExit("specialized handoffs must preserve aws_lake and aws_s3_sal")
for provider_type, item in specialized.items():
    if item.get("automation") != "ui_handoff":
        raise SystemExit(f"{provider_type} must remain ui_handoff")
    if provider_type not in specialized_text:
        raise SystemExit(f"specialized handoff artifact is missing {provider_type}")
if "generic `aws_s3`" not in specialized_text:
    raise SystemExit("specialized handoff must reject generic aws_s3 substitution")

catalog_keys = {
    item.get("key") for item in metadata.get("amazon_s3_data_catalog_options", [])
}
if catalog_keys != {"aws_glue", "iceberg_rest", "splunk_native"}:
    raise SystemExit("Amazon S3 catalog options are incomplete")

legacy = metadata.get("legacy_fss3", {})
if legacy.get("provider_type") != "aws_s3":
    raise SystemExit("legacy FSS3 provider type must remain aws_s3")
if legacy.get("lifecycle") != "legacy_phased_deprecation":
    raise SystemExit("legacy FSS3 lifecycle must be legacy_phased_deprecation")
if legacy.get("automation") != "rendered_migration_evidence_only":
    raise SystemExit("legacy FSS3 automation must remain migration evidence only")
if "phased deprecation" not in legacy_text:
    raise SystemExit("legacy FSS3 migration artifact is missing phased-deprecation guidance")

legacy_providers = metadata.get("providers", {}).get("amazon_s3", [])
if legacy_providers:
    for provider in legacy_providers:
        if provider.get("automation") != "rendered_migration_evidence_only":
            raise SystemExit("legacy FSS3 provider metadata must remain migration evidence only")
    warnings = "\n".join(metadata.get("warnings", []))
    if "phased-deprecation" not in warnings:
        raise SystemExit("legacy FSS3 providers require a phased-deprecation warning")
PY
    then
        missing+=("federation lifecycle metadata/handoff contract")
        ok=false
    fi
fi

# Legacy FSS3 evidence must never become input to generated mutation scripts.
# FSS2S providers can legitimately use the same REST collection, so for mixed
# specs we assert that no legacy provider name or evidence directory is wired
# into either apply path. Legacy-only specs must render explicit refusal scripts.
if [[ -f "${render_dir}/metadata.json" && -f "${render_dir}/apply-rest.sh" && -f "${render_dir}/apply-search-head.sh" ]]; then
    if ! python3 - \
        "${render_dir}/metadata.json" \
        "${render_dir}/apply-rest.sh" \
        "${render_dir}/apply-search-head.sh" <<'PY'
import ast
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rest_apply = Path(sys.argv[2]).read_text(encoding="utf-8")
local_apply = Path(sys.argv[3]).read_text(encoding="utf-8")
legacy = metadata.get("providers", {}).get("amazon_s3", [])
s2s = metadata.get("providers", {}).get("splunk_to_splunk", [])

if legacy:
    for script_name, text in (("apply-rest.sh", rest_apply), ("apply-search-head.sh", local_apply)):
        if "aws-s3-providers/" in text:
            raise SystemExit(f"{script_name} must not consume legacy FSS3 evidence files")
    if "'type': 'aws_s3'" in rest_apply or '"type": "aws_s3"' in rest_apply:
        raise SystemExit("apply-rest.sh contains a legacy FSS3 provider payload")
    # In mixed plans, structurally inspect the embedded Python literals instead
    # of substring-matching provider names against generic script prose.
    if s2s:
        marker = "python3 - <<'PY'\n"
        if marker not in rest_apply or "\nPY\n" not in rest_apply:
            raise SystemExit("mixed-plan apply-rest.sh is missing its embedded FSS2S program")
        python_source = rest_apply.split(marker, 1)[1].rsplit("\nPY\n", 1)[0]
        tree = ast.parse(python_source)
        literals = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in {"s2s_payloads", "index_payloads"}:
                    literals[node.targets[0].id] = ast.literal_eval(node.value)
        legacy_names = {provider.get("name") for provider in legacy}
        applied_provider_names = {
            entry.get("name") for entry in literals.get("s2s_payloads", [])
        }
        applied_index_providers = {
            entry.get("federated.provider") for entry in literals.get("index_payloads", [])
        }
        if legacy_names & (applied_provider_names | applied_index_providers):
            raise SystemExit("apply-rest.sh structurally includes a legacy FSS3 provider or index")
    if not s2s:
        for script_name, text in (("apply-rest.sh", rest_apply), ("apply-search-head.sh", local_apply)):
            if "HANDOFF ONLY" not in text or "exit 2" not in text:
                raise SystemExit(f"legacy-only {script_name} must refuse mutation")
        if "/services/data/federated/provider" in rest_apply or "/services/data/federated/index" in rest_apply:
            raise SystemExit("legacy-only REST apply must not contain provider/index CRUD endpoints")
PY
    then
        missing+=("legacy FSS3 migration-only apply boundary")
        ok=false
    fi
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
