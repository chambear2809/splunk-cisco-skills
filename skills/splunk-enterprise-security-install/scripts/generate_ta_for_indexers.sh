#!/usr/bin/env bash
# Extract Splunk_TA_ForIndexers from a local ES package so it can be staged on a
# cluster manager and deployed to indexer peers. The ES package ships a Splunk
# Cloud-variant Splunk_TA_ForIndexers tarball under
# SplunkEnterpriseSecuritySuite/install/splunkcloud/splunk_app_es/. This helper
# copies (or repackages) that tarball into a target directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Reset credential-helper load guards if the functions they define are not yet
# available. This handles nested-shell cases where a parent process (for
# example, a bats setup block) exported the guard variables but did not also
# export the helper function definitions.
if ! declare -F require_arg >/dev/null 2>&1; then
    unset _CRED_HELPERS_LOADED _CREDENTIALS_LOADED _REST_HELPERS_LOADED \
        _ACS_HELPERS_LOADED _SPLUNKBASE_HELPERS_LOADED \
        _CONFIGURE_ACCOUNT_HELPERS_LOADED _DEPLOYMENT_HELPERS_LOADED \
        _REGISTRY_HELPERS_LOADED _HOST_BOOTSTRAP_HELPERS_LOADED
fi
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

ES_PACKAGE=""
OUTPUT_DIR=""
FORCE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk_TA_ForIndexers Generator

Usage: $(basename "$0") [OPTIONS]

Options:
  --package PATH    Path to the ES .spl/.tgz package (default: newest in splunk-ta/)
  --output-dir DIR  Directory to write the extracted tarball (default: ta-for-indexers-rendered/)
  --force           Overwrite an existing output file
  --help            Show this help text

Exits 0 on success and prints the absolute path of the generated tarball on the
last stdout line so downstream callers can capture it.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --package)
            require_arg "$1" $# || exit 1
            ES_PACKAGE="$2"
            shift 2
            ;;
        --output-dir)
            require_arg "$1" $# || exit 1
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --force) FORCE=true; shift ;;
        --help|-h) usage 0 ;;
        *)
            log "ERROR: Unknown option '$1'"
            usage 1
            ;;
    esac
done

REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

find_default_package() {
    local candidate
    candidate="$(find "${REPO_ROOT}/splunk-ta" -maxdepth 1 -type f \
        \( -name 'splunk-enterprise-security_*.spl' -o -name 'splunk-enterprise-security_*.tgz' -o -name 'splunk-enterprise-security_*.tar.gz' \) \
        2>/dev/null | sort -V | tail -1)"
    printf '%s' "${candidate}"
}

if [[ -z "${ES_PACKAGE}" ]]; then
    ES_PACKAGE="$(find_default_package)"
fi

if [[ -z "${ES_PACKAGE}" || ! -f "${ES_PACKAGE}" ]]; then
    log "ERROR: ES package not found. Pass --package PATH or cache a package under splunk-ta/."
    exit 1
fi

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${REPO_ROOT}/ta-for-indexers-rendered"
fi

mkdir -p "${OUTPUT_DIR}"

log "Extracting Splunk_TA_ForIndexers from ${ES_PACKAGE}"

# The member name inside the ES tarball looks like:
#   SplunkEnterpriseSecuritySuite/install/splunkcloud/splunk_app_es/Splunk_TA_ForIndexers-<version>.spl
# When more than one matching member exists (rare; happens with archives that
# bundle preview or rollback variants), pick the highest dotted version so a
# fresh ES tarball does not silently install an older TA. Members without a
# parseable version sort lexically last as a stable tiebreaker.
MEMBER_NAME="$(
python3 - "${ES_PACKAGE}" <<'PY'
import re
import sys
import tarfile

VERSION_RE = re.compile(r"Splunk_TA_ForIndexers-(\d+(?:\.\d+)+)")

def version_key(name: str) -> tuple[tuple[int, ...], str]:
    base = name.rsplit("/", 1)[-1]
    match = VERSION_RE.search(base)
    if not match:
        return ((), base)
    parts = tuple(int(x) for x in match.group(1).split("."))
    return (parts, base)

with tarfile.open(sys.argv[1]) as tf:
    candidates = [
        name for name in tf.getnames()
        if name.rsplit("/", 1)[-1].startswith("Splunk_TA_ForIndexers")
        and name.endswith((".spl", ".tgz", ".tar.gz"))
    ]
    if not candidates:
        sys.exit(0)
    candidates.sort(key=version_key)
    selected = candidates[-1]
    if len(candidates) > 1:
        skipped = [c for c in candidates if c != selected]
        sys.stderr.write(
            f"INFO: multiple Splunk_TA_ForIndexers members found; selected highest version: {selected}\n"
            f"      skipped: {', '.join(skipped)}\n"
        )
    print(selected, end="")
PY
)"

if [[ -z "${MEMBER_NAME}" ]]; then
    log "ERROR: Splunk_TA_ForIndexers was not found inside ${ES_PACKAGE}."
    log "       Expected a member named Splunk_TA_ForIndexers-*.spl|.tgz|.tar.gz."
    exit 1
fi

OUTPUT_BASENAME="$(basename "${MEMBER_NAME}")"
OUTPUT_PATH="${OUTPUT_DIR}/${OUTPUT_BASENAME}"

if [[ -e "${OUTPUT_PATH}" && "${FORCE}" != "true" ]]; then
    log "ERROR: ${OUTPUT_PATH} already exists. Pass --force to overwrite."
    exit 1
fi

python3 - "${ES_PACKAGE}" "${MEMBER_NAME}" "${OUTPUT_PATH}" <<'PY'
import sys
import tarfile

es_path, member, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
with tarfile.open(es_path) as tf:
    src = tf.extractfile(member)
    if src is None:
        raise SystemExit(f"Could not extract {member} from {es_path}")
    with open(out_path, "wb") as dest:
        while True:
            chunk = src.read(65536)
            if not chunk:
                break
            dest.write(chunk)
PY

chmod 0644 "${OUTPUT_PATH}"

log "Wrote ${OUTPUT_PATH}"
log ""
log "Next steps (operator-managed; these require SSH to the cluster manager):"
log "  1. Copy ${OUTPUT_PATH} to the cluster manager."
log "  2. Extract it under \$SPLUNK_HOME/etc/manager-apps/Splunk_TA_ForIndexers."
log "  3. Apply the cluster bundle, e.g.:"
log "       splunk apply cluster-bundle --answer-yes"
log "     or use the setup.sh --deploy-ta-for-indexers CM_URI flag to POST"
log "     /services/cluster/manager/control/control/apply-bundle via REST."
log ""

# Final line is the absolute path so downstream shells can capture it.
printf '%s\n' "${OUTPUT_PATH}"
