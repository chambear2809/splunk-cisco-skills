#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

usage() {
    cat <<EOF
Batch-uninstall apps from Splunk Cloud with preflight and verified completion.

Every target is validated and its current ACS version is read before the batch,
then exact state/version is revalidated immediately before each mutation. The
exact plan is printed, and non-interactive execution requires --yes. ACS is
always attempted first. Success requires definitive bounded ACS absence; a REST
404 alone is insufficient, and a present/disagreeing channel wins. Direct
search-tier REST DELETE is disabled unless the
separate --accept-rest-fallback acknowledgement is supplied; that fallback can
desynchronize ACS/SHC-managed state or affect only one search-head member.

Usage: $(basename "$0") [OPTIONS] <app_name> [app_name...]

Options:
  --yes                    Confirm the printed destructive plan non-interactively
  --accept-rest-fallback   Permit direct REST DELETE only if ACS leaves an app
                           present after bounded verification (topology risk)
  --no-restart             Skip ACS restart checks
  --verify-attempts N      Bounded absence probes per phase (default: 6)
  --verify-interval SEC    Seconds between probes (default: 5; may be 0)
  --evidence-file PATH     Private JSON result/recovery evidence path
  --help                   Show this help

Example:
  $(basename "$0") --yes Splunk_TA_Cisco_Intersight Splunk_TA_cisco_meraki
EOF
    exit "${1:-0}"
}

APP_NAMES=()
RESTART=true
ASSUME_YES=false
ACCEPT_REST_FALLBACK=false
VERIFY_ATTEMPTS=6
VERIFY_INTERVAL=5
EVIDENCE_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) ASSUME_YES=true; shift ;;
        --accept-rest-fallback) ACCEPT_REST_FALLBACK=true; shift ;;
        --no-restart) RESTART=false; shift ;;
        --verify-attempts) require_arg "$1" $# || exit 1; VERIFY_ATTEMPTS="$2"; shift 2 ;;
        --verify-interval) require_arg "$1" $# || exit 1; VERIFY_INTERVAL="$2"; shift 2 ;;
        --evidence-file) require_arg "$1" $# || exit 1; EVIDENCE_FILE="$2"; shift 2 ;;
        --help) usage 0 ;;
        --*) log "ERROR: Unknown option: $1"; usage 1 ;;
        *) APP_NAMES+=("$1"); shift ;;
    esac
done

if (( ${#APP_NAMES[@]} == 0 )); then
    log "ERROR: At least one app name is required."
    usage 1
fi
if [[ ! "${VERIFY_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]] || (( VERIFY_ATTEMPTS > 60 )); then
    log "ERROR: --verify-attempts must be an integer from 1 through 60."
    exit 1
fi
if [[ ! "${VERIFY_INTERVAL}" =~ ^[0-9]+$ ]] || (( VERIFY_INTERVAL > 60 )); then
    log "ERROR: --verify-interval must be an integer from 0 through 60."
    exit 1
fi

validate_app_name() {
    local app="$1"
    [[ -n "${app}" && "${app}" != "." && "${app}" != ".." ]] || return 1
    [[ "${app}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]
}

for index in "${!APP_NAMES[@]}"; do
    app="${APP_NAMES[$index]}"
    if ! validate_app_name "${app}"; then
        log "ERROR: Invalid app name at argument $((index + 1)). Use 1-128 letters, numbers, underscore, dot, or hyphen; the first character cannot be dot/hyphen."
        exit 1
    fi
done
for ((i = 0; i < ${#APP_NAMES[@]}; i++)); do
    for ((j = i + 1; j < ${#APP_NAMES[@]}; j++)); do
        if [[ "${APP_NAMES[$i]}" == "${APP_NAMES[$j]}" ]]; then
            log "ERROR: Duplicate app target '${APP_NAMES[$i]}' is not allowed."
            exit 1
        fi
    done
done

if ! is_splunk_cloud; then
    log "ERROR: This script is for Splunk Cloud only."
    exit 1
fi

if [[ -z "${EVIDENCE_FILE}" ]]; then
    EVIDENCE_FILE="${TMPDIR:-/tmp}/splunk-cloud-batch-uninstall-evidence-$(date -u '+%Y%m%dT%H%M%SZ')-$$.json"
fi

PLAN_VERSIONS=()
PREFLIGHT_SOURCES=()
ACS_RESULTS=()
REST_RESULTS=()
FINAL_RESULTS=()
RECOVERY_ACTIONS=()
for app in "${APP_NAMES[@]}"; do
    PLAN_VERSIONS+=("unknown")
    PREFLIGHT_SOURCES+=("unverified")
    ACS_RESULTS+=("not-attempted")
    REST_RESULTS+=("not-attempted")
    FINAL_RESULTS+=("not-verified")
    RECOVERY_ACTIONS+=("No mutation attempted.")
done

EVIDENCE_WRITTEN=false
MUTATION_STARTED=false
RUN_SUMMARY="Initialization did not complete."

sanitize_evidence_field() {
    local value="$1"
    value="${value//$'\t'/ }"
    value="${value//$'\r'/ }"
    value="${value//$'\n'/ }"
    printf '%s' "${value}"
}

write_evidence() {
    local result="$1" exit_code="$2" summary="$3" staging index evidence_rc
    staging="$(mktemp "${TMPDIR:-/tmp}/cloud-uninstall-evidence.XXXXXX")"
    chmod 600 "${staging}"
    for index in "${!APP_NAMES[@]}"; do
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$(sanitize_evidence_field "${APP_NAMES[$index]}")" \
            "$(sanitize_evidence_field "${PLAN_VERSIONS[$index]}")" \
            "$(sanitize_evidence_field "${PREFLIGHT_SOURCES[$index]}")" \
            "$(sanitize_evidence_field "${ACS_RESULTS[$index]}")" \
            "$(sanitize_evidence_field "${REST_RESULTS[$index]}")" \
            "$(sanitize_evidence_field "${FINAL_RESULTS[$index]}")" \
            "$(sanitize_evidence_field "${RECOVERY_ACTIONS[$index]}")" >> "${staging}"
    done
    set +e
    EVIDENCE_RESULT="${result}" EVIDENCE_EXIT_CODE="${exit_code}" \
    EVIDENCE_SUMMARY="$(sanitize_evidence_field "${summary}")" \
    EVIDENCE_RESTART="${RESTART}" EVIDENCE_REST_FALLBACK="${ACCEPT_REST_FALLBACK}" \
    EVIDENCE_MUTATION_STARTED="${MUTATION_STARTED}" \
    EVIDENCE_STACK="${SPLUNK_CLOUD_STACK:-}" \
    EVIDENCE_SEARCH_HEAD="${SPLUNK_CLOUD_SEARCH_HEAD:-}" \
    EVIDENCE_VERIFY_ATTEMPTS="${VERIFY_ATTEMPTS}" \
    EVIDENCE_VERIFY_INTERVAL="${VERIFY_INTERVAL}" \
    python3 - "${staging}" "${EVIDENCE_FILE}" <<'PY'
import json
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
import sys

source = Path(sys.argv[1])
destination = Path(os.path.abspath(os.fspath(Path(sys.argv[2]).expanduser())))
if not destination.name or destination.name in {".", ".."}:
    raise SystemExit(f"ERROR: invalid evidence file path: {destination}")
parent = destination.parent
# macOS exposes /var and /tmp as fixed root-owned aliases into /private. Resolve
# only those OS aliases before the dirfd walk; every user-controlled symlink is
# still rejected by O_NOFOLLOW below.
if sys.platform == "darwin" and parent.is_absolute() and len(parent.parts) > 1:
    first_component = parent.parts[1]
    if first_component in {"tmp", "var"}:
        alias = Path(os.path.sep) / first_component
        try:
            alias_metadata = alias.lstat()
            alias_target = alias.resolve(strict=True)
        except OSError:
            pass
        else:
            if (
                stat.S_ISLNK(alias_metadata.st_mode)
                and alias_metadata.st_uid == 0
                and alias_target.is_dir()
                and alias_target.parts[:2] == (os.path.sep, "private")
            ):
                parent = alias_target.joinpath(*parent.parts[2:])
rows = []
for line in source.read_text(encoding="utf-8").splitlines():
    fields = line.split("\t")
    if len(fields) != 7:
        raise SystemExit("ERROR: invalid uninstall evidence staging row")
    rows.append(
        {
            "app": fields[0],
            "preflight_version": fields[1],
            "preflight_source": fields[2],
            "acs_uninstall": fields[3],
            "rest_fallback": fields[4],
            "final_verification": fields[5],
            "recovery_action": fields[6],
        }
    )
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "result": os.environ["EVIDENCE_RESULT"],
    "exit_code": int(os.environ["EVIDENCE_EXIT_CODE"]),
    "summary": os.environ["EVIDENCE_SUMMARY"],
    "mutation_started": os.environ["EVIDENCE_MUTATION_STARTED"] == "true",
    "restart_enabled": os.environ["EVIDENCE_RESTART"] == "true",
    "rest_fallback_accepted": os.environ["EVIDENCE_REST_FALLBACK"] == "true",
    "target": {
        "stack": os.environ["EVIDENCE_STACK"],
        "search_head": os.environ["EVIDENCE_SEARCH_HEAD"] or None,
    },
    "verification_policy": {
        "attempts": int(os.environ["EVIDENCE_VERIFY_ATTEMPTS"]),
        "interval_seconds": int(os.environ["EVIDENCE_VERIFY_INTERVAL"]),
    },
    "apps": rows,
}

if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
    raise SystemExit("ERROR: secure evidence writes require O_NOFOLLOW and O_DIRECTORY")
directory_flags = os.O_RDONLY | os.O_DIRECTORY
nofollow = os.O_NOFOLLOW
parent_fd = os.open(os.path.sep, directory_flags)
temporary = ""
fd = -1
try:
    for component in parent.parts[1:]:
        if component in {"", ".", ".."}:
            raise SystemExit(
                f"ERROR: invalid evidence parent component: {component!r}"
            )
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            next_fd = os.open(
                component,
                directory_flags | nofollow,
                dir_fd=parent_fd,
            )
        except OSError as error:
            raise SystemExit(
                "ERROR: refusing symlink/non-directory evidence parent "
                f"component {component!r}: {error}"
            ) from error
        os.close(parent_fd)
        parent_fd = next_fd

    try:
        existing = os.stat(destination.name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and stat.S_ISLNK(existing.st_mode):
        raise SystemExit(f"ERROR: refusing symlink evidence file: {destination}")
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise SystemExit(f"ERROR: refusing non-regular evidence file: {destination}")

    for _ in range(128):
        temporary = f".uninstall-evidence.{secrets.token_hex(12)}"
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
                dir_fd=parent_fd,
            )
            break
        except FileExistsError:
            continue
    else:
        raise SystemExit("ERROR: could not allocate a private evidence staging file")

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        fd = -1
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(
        temporary,
        destination.name,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
    )
    temporary = ""
    os.fsync(parent_fd)
except BaseException:
    if fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass
    if temporary:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    raise
finally:
    if parent_fd >= 0:
        os.close(parent_fd)
PY
    evidence_rc=$?
    set -e
    rm -f -- "${staging}"
    if (( evidence_rc != 0 )); then
        return "${evidence_rc}"
    fi
    EVIDENCE_WRITTEN=true
    log "Evidence: ${EVIDENCE_FILE}"
}

exit_evidence_trap() {
    local code=$?
    trap - EXIT INT TERM HUP
    if [[ "${EVIDENCE_WRITTEN}" != "true" ]]; then
        write_evidence "failed" "${code}" "${RUN_SUMMARY}" || true
    fi
    exit "${code}"
}
trap exit_evidence_trap EXIT
trap 'RUN_SUMMARY="Interrupted by SIGINT."; exit 130' INT
trap 'RUN_SUMMARY="Interrupted by SIGTERM."; exit 143' TERM
trap 'RUN_SUMMARY="Interrupted by SIGHUP."; exit 129' HUP

refresh_verify_session() {
    SK_VERIFY=""
    load_splunk_credentials 2>/dev/null || return 1
    if [[ -z "${SPLUNK_URI:-}" ]] || [[ "${SPLUNK_URI}" != *".splunkcloud.com"* ]]; then
        return 1
    fi
    SK_VERIFY="$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)"
    [[ -n "${SK_VERIFY}" ]]
}

ACS_PROBE_STATE="ambiguous"
ACS_PROBE_VERSION=""
ACS_PROBE_STATUS=""
ACS_PROBE_DETAIL=""

acs_output_proves_not_found() {
    local app="$1" raw="$2"
    ACS_NOT_FOUND_APP="${app}" ACS_NOT_FOUND_RAW="${raw}" python3 - <<'PY'
import json
import os
import re

raw = os.environ.get("ACS_NOT_FOUND_RAW", "").strip()
requested_app = os.environ.get("ACS_NOT_FOUND_APP", "")


def top_level_http_404(value):
    if not isinstance(value, dict):
        return False
    return any(
        str(value.get(key, "")).strip() == "404"
        for key in (
            "code",
            "status",
            "statusCode",
            "status_code",
            "httpStatus",
            "http_status",
        )
    )


def known_acs_404_envelope(value):
    candidates = value if isinstance(value, list) else [value]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if isinstance(value, list) and str(candidate.get("type", "")).lower() != "http":
            continue
        if top_level_http_404(candidate):
            return True
        if str(candidate.get("type", "")).lower() != "http":
            continue
        response = candidate.get("response")
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except Exception:
                response = None
        if top_level_http_404(response):
            return True
    return False


try:
    document = json.loads(raw)
except Exception:
    document = None
if document is not None and known_acs_404_envelope(document):
    raise SystemExit(0)

plain = " ".join(raw.split())
plain = re.sub(r"^error:\s*", "", plain, flags=re.IGNORECASE)
generic = {
    "app not found",
    "application not found",
    "resource not found",
    "not found",
    "no such app",
    "no such application",
    "app does not exist",
    "application does not exist",
}
if plain.rstrip(".").lower() in generic:
    raise SystemExit(0)

identifier = r"([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})"
named_patterns = (
    rf"^(?:app(?:lication)?|resource)\s+['\"\[]?{identifier}['\"\]]?\s+(?:is\s+|was\s+)?not[ -]?found[.!]?$",
    rf"^no such app(?:lication)?[: ]+['\"\[]?{identifier}['\"\]]?[.!]?$",
    rf"^(?:app(?:lication)?|resource)\s+['\"\[]?{identifier}['\"\]]?\s+does not exist[.!]?$",
    rf"^not[ -]?found:\s*(?:app(?:lication)?|resource)\s+['\"\[]?{identifier}['\"\]]?[.!]?$",
)
for pattern in named_patterns:
    match = re.fullmatch(pattern, plain, flags=re.IGNORECASE)
    if match:
        raise SystemExit(0 if match.group(1) == requested_app else 1)
raise SystemExit(1)
PY
}

probe_app_via_acs() {
    local app="$1" raw rc json metadata valid name version status
    ACS_PROBE_STATE="ambiguous"
    ACS_PROBE_VERSION=""
    ACS_PROBE_STATUS=""
    ACS_PROBE_DETAIL=""
    set +e
    raw="$(acs_command apps describe "${app}" 2>&1)"
    rc=$?
    set -e
    if (( rc == 0 )); then
        json="$(printf '%s' "${raw}" | acs_extract_http_response_json)"
        metadata="$(printf '%s' "${json}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("0|||", end="")
    raise SystemExit(0)
if isinstance(data, dict) and isinstance(data.get("app"), dict):
    data = data["app"]
if not isinstance(data, dict):
    print("0|||", end="")
    raise SystemExit(0)
spec = data.get("spec") if isinstance(data.get("spec"), dict) else {}
name = data.get("name") or data.get("appID") or spec.get("name") or ""
version = data.get("version") or spec.get("version") or ""
status = data.get("status") or spec.get("status") or ""
values = (name, version, status)
if not isinstance(name, str) or not name or any(
    not isinstance(value, str) or "|" in value or "\\n" in value or "\\r" in value
    for value in values
):
    print("0|||", end="")
else:
    print(f"1|{name}|{version}|{status}", end="")
')"
        IFS='|' read -r valid name version status <<< "${metadata}"
        if [[ "${valid}" != "1" ]]; then
            ACS_PROBE_DETAIL="ACS describe returned rc=0 without a valid exact app record."
            return 0
        fi
        if [[ "${name}" != "${app}" ]]; then
            ACS_PROBE_DETAIL="ACS returned a different app identity '${name}'."
            return 0
        fi
        ACS_PROBE_STATE="present"
        ACS_PROBE_VERSION="${version}"
        ACS_PROBE_STATUS="${status}"
        ACS_PROBE_DETAIL="ACS describe rc=0."
        return 0
    fi
    if acs_output_proves_not_found "${app}" "${raw}"; then
        ACS_PROBE_STATE="absent"
        ACS_PROBE_DETAIL="ACS describe definitively reported not found (rc=${rc})."
    else
        ACS_PROBE_DETAIL="ACS describe was unavailable or ambiguous (rc=${rc})."
    fi
}

REST_PROBE_STATE="unavailable"
REST_PROBE_VERSION=""
REST_PROBE_DETAIL=""

probe_app_via_rest() {
    local app="$1" encoded response rc code body metadata name version
    REST_PROBE_STATE="unavailable"
    REST_PROBE_VERSION=""
    REST_PROBE_DETAIL="Search-tier REST verification is unavailable."
    [[ "${REST_AVAILABLE}" == "true" ]] || return 0
    encoded="$(_urlencode "${app}")" || return 0
    set +e
    response="$(splunk_curl "${SK_VERIFY}" --connect-timeout 5 --max-time 15 \
        "${SPLUNK_URI}/services/apps/local/${encoded}?output_mode=json" \
        -w '\n%{http_code}' 2>/dev/null)"
    rc=$?
    set -e
    code="$(printf '%s\n' "${response}" | tail -1)"
    body="$(printf '%s\n' "${response}" | sed '$d')"
    if (( rc != 0 )) || [[ ! "${code}" =~ ^[0-9]{3}$ ]]; then
        REST_PROBE_STATE="ambiguous"
        REST_PROBE_DETAIL="REST lookup transport failed (rc=${rc}, HTTP ${code:-000})."
        return 0
    fi
    case "${code}" in
        404)
            REST_PROBE_STATE="absent"
            REST_PROBE_DETAIL="REST returned HTTP 404."
            ;;
        200)
            metadata="$(printf '%s' "${body}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    entries = data.get("entry", []) if isinstance(data, dict) else []
    entry = entries[0] if len(entries) == 1 and isinstance(entries[0], dict) else {}
    content = entry.get("content") if isinstance(entry.get("content"), dict) else {}
    name = entry.get("name", "")
    version = content.get("version", "")
    if not isinstance(name, str) or not name or not isinstance(version, str):
        print("0||", end="")
    elif any(character in name or character in version for character in ("|", "\\n", "\\r")):
        print("0||", end="")
    else:
        print("1|{}|{}".format(name, version), end="")
except Exception:
    print("0||", end="")
')"
            IFS='|' read -r valid name version <<< "${metadata}"
            if [[ "${valid}" != "1" ]]; then
                REST_PROBE_STATE="ambiguous"
                REST_PROBE_DETAIL="REST returned HTTP 200 without one valid exact app record."
            elif [[ "${name}" != "${app}" ]]; then
                REST_PROBE_STATE="ambiguous"
                REST_PROBE_DETAIL="REST returned a different app identity '${name}'."
            else
                REST_PROBE_STATE="present"
                REST_PROBE_VERSION="${version}"
                REST_PROBE_DETAIL="REST returned HTTP 200."
            fi
            ;;
        *)
            REST_PROBE_STATE="ambiguous"
            REST_PROBE_DETAIL="REST lookup returned HTTP ${code}."
            ;;
    esac
}

VERIFY_STATE="ambiguous"
VERIFY_DETAIL=""

verify_app_absent_bounded() {
    local app="$1" attempt
    VERIFY_STATE="ambiguous"
    VERIFY_DETAIL="No definitive verification result."
    for ((attempt = 1; attempt <= VERIFY_ATTEMPTS; attempt++)); do
        probe_app_via_acs "${app}"
        probe_app_via_rest "${app}"
        if [[ "${ACS_PROBE_STATE}" == "present" && "${REST_PROBE_STATE}" == "absent" ]] || \
           [[ "${ACS_PROBE_STATE}" == "absent" && "${REST_PROBE_STATE}" == "present" ]]; then
            VERIFY_STATE="disagreement"
            VERIFY_DETAIL="Attempt ${attempt}/${VERIFY_ATTEMPTS}: channel disagreement (ACS=${ACS_PROBE_STATE}, REST=${REST_PROBE_STATE}); a present channel wins."
        elif [[ "${ACS_PROBE_STATE}" == "present" || "${REST_PROBE_STATE}" == "present" ]]; then
            VERIFY_STATE="present"
            VERIFY_DETAIL="Attempt ${attempt}/${VERIFY_ATTEMPTS}: ACS=${ACS_PROBE_STATE}, REST=${REST_PROBE_STATE}."
        elif [[ "${ACS_PROBE_STATE}" == "absent" ]]; then
            VERIFY_STATE="absent"
            VERIFY_DETAIL="Attempt ${attempt}/${VERIFY_ATTEMPTS}: definitive ACS absence; REST=${REST_PROBE_STATE}."
            return 0
        elif [[ "${REST_PROBE_STATE}" == "absent" ]]; then
            VERIFY_STATE="ambiguous"
            VERIFY_DETAIL="Attempt ${attempt}/${VERIFY_ATTEMPTS}: REST-only HTTP 404 is insufficient because ACS=${ACS_PROBE_STATE}."
        else
            VERIFY_STATE="ambiguous"
            VERIFY_DETAIL="Attempt ${attempt}/${VERIFY_ATTEMPTS}: ACS=${ACS_PROBE_STATE}, REST=${REST_PROBE_STATE}."
        fi
        if (( attempt < VERIFY_ATTEMPTS && VERIFY_INTERVAL > 0 )); then
            sleep "${VERIFY_INTERVAL}"
        fi
    done
    [[ "${VERIFY_STATE}" == "present" || "${VERIFY_STATE}" == "disagreement" ]] && return 1
    return 2
}

delete_app_via_rest() {
    local app="$1" encoded response rc code
    encoded="$(_urlencode "${app}")" || return 1
    set +e
    response="$(splunk_curl "${SK_VERIFY}" --connect-timeout 10 --max-time 60 \
        -X DELETE "${SPLUNK_URI}/services/apps/local/${encoded}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null)"
    rc=$?
    set -e
    code="${response:-000}"
    if (( rc == 0 )) && [[ "${code}" =~ ^(200|204|404)$ ]]; then
        REST_DELETE_RESULT="accepted-http-${code}"
        return 0
    fi
    REST_DELETE_RESULT="ambiguous-rc-${rc}-http-${code}"
    return 1
}

is_safe_exact_version() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$ ]]
}

acs_status_is_stable_for_removal() {
    local normalized
    normalized="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "${normalized}" in
        ""|installed|updated|active|completed|complete|ready|enabled|success|succeeded)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

PRESENT_CHECK_VERSION=""
PRESENT_CHECK_SOURCE="unverified"
PRESENT_CHECK_DETAIL=""

check_app_present_exact() {
    local app="$1" expected_version="${2:-}"
    PRESENT_CHECK_VERSION=""
    PRESENT_CHECK_SOURCE="unverified"
    PRESENT_CHECK_DETAIL=""

    probe_app_via_acs "${app}"
    probe_app_via_rest "${app}"

    if [[ "${ACS_PROBE_STATE}" != "present" ]]; then
        PRESENT_CHECK_DETAIL="ACS must authoritatively report the app present; ACS=${ACS_PROBE_STATE}. ${ACS_PROBE_DETAIL} REST=${REST_PROBE_STATE}."
        return 1
    fi
    if ! is_safe_exact_version "${ACS_PROBE_VERSION}"; then
        PRESENT_CHECK_DETAIL="ACS reported the app present without a valid exact version."
        return 1
    fi
    if [[ -n "${expected_version}" && "${ACS_PROBE_VERSION}" != "${expected_version}" ]]; then
        PRESENT_CHECK_DETAIL="ACS version changed from planned ${expected_version} to ${ACS_PROBE_VERSION}."
        return 1
    fi
    if ! acs_status_is_stable_for_removal "${ACS_PROBE_STATUS}"; then
        PRESENT_CHECK_DETAIL="ACS status '${ACS_PROBE_STATUS}' is not a recognized stable removal state."
        return 1
    fi

    PRESENT_CHECK_VERSION="${ACS_PROBE_VERSION}"
    PRESENT_CHECK_SOURCE="ACS"
    case "${REST_PROBE_STATE}" in
        present)
            if ! is_safe_exact_version "${REST_PROBE_VERSION}"; then
                PRESENT_CHECK_DETAIL="REST reported the app present without a valid exact version."
                return 1
            fi
            if [[ "${REST_PROBE_VERSION}" != "${ACS_PROBE_VERSION}" ]]; then
                PRESENT_CHECK_DETAIL="Version disagreement: ACS=${ACS_PROBE_VERSION}, REST=${REST_PROBE_VERSION}."
                return 1
            fi
            PRESENT_CHECK_SOURCE="ACS+REST"
            ;;
        absent)
            PRESENT_CHECK_DETAIL="Presence disagreement: ACS=present, REST=absent."
            return 1
            ;;
        ambiguous)
            PRESENT_CHECK_DETAIL="REST was configured but returned ambiguous state. ${REST_PROBE_DETAIL}"
            return 1
            ;;
        unavailable)
            ;;
        *)
            PRESENT_CHECK_DETAIL="REST returned an unrecognized probe state '${REST_PROBE_STATE}'."
            return 1
            ;;
    esac

    PRESENT_CHECK_DETAIL="Exact present state verified at version ${PRESENT_CHECK_VERSION} via ${PRESENT_CHECK_SOURCE}."
}

REST_FALLBACK_CHECK_DETAIL=""

check_rest_fallback_exact() {
    local app="$1" expected_version="$2"
    REST_FALLBACK_CHECK_DETAIL=""
    probe_app_via_acs "${app}"
    probe_app_via_rest "${app}"

    if [[ "${ACS_PROBE_STATE}" == "ambiguous" ]]; then
        REST_FALLBACK_CHECK_DETAIL="ACS state is ambiguous immediately before REST mutation. ${ACS_PROBE_DETAIL}"
        return 1
    fi
    if [[ "${ACS_PROBE_STATE}" == "present" ]]; then
        if [[ "${ACS_PROBE_VERSION}" != "${expected_version}" ]] || ! is_safe_exact_version "${ACS_PROBE_VERSION}"; then
            REST_FALLBACK_CHECK_DETAIL="ACS present version does not match planned ${expected_version} (actual=${ACS_PROBE_VERSION:-unknown})."
            return 1
        fi
        if ! acs_status_is_stable_for_removal "${ACS_PROBE_STATUS}"; then
            REST_FALLBACK_CHECK_DETAIL="ACS status '${ACS_PROBE_STATUS}' is not stable immediately before REST mutation."
            return 1
        fi
    fi
    if [[ "${REST_PROBE_STATE}" != "present" ]]; then
        REST_FALLBACK_CHECK_DETAIL="REST must report the exact app present immediately before direct DELETE; REST=${REST_PROBE_STATE}. ${REST_PROBE_DETAIL}"
        return 1
    fi
    if [[ "${REST_PROBE_VERSION}" != "${expected_version}" ]] || ! is_safe_exact_version "${REST_PROBE_VERSION}"; then
        REST_FALLBACK_CHECK_DETAIL="REST present version does not match planned ${expected_version} (actual=${REST_PROBE_VERSION:-unknown})."
        return 1
    fi
    REST_FALLBACK_CHECK_DETAIL="Exact REST fallback target revalidated at version ${expected_version}; ACS=${ACS_PROBE_STATE}."
}

acs_prepare_context || { RUN_SUMMARY="ACS context preparation failed before mutation."; exit 1; }
REST_AVAILABLE=false
SK_VERIFY=""
if refresh_verify_session; then
    REST_AVAILABLE=true
fi

log "=== Cloud Batch Uninstall Preflight ==="
preflight_failed=false
for index in "${!APP_NAMES[@]}"; do
    app="${APP_NAMES[$index]}"
    if check_app_present_exact "${app}"; then
        PLAN_VERSIONS[index]="${PRESENT_CHECK_VERSION}"
        PREFLIGHT_SOURCES[index]="${PRESENT_CHECK_SOURCE}"
        log "  VERIFIED: ${app} version=${PRESENT_CHECK_VERSION} source=${PRESENT_CHECK_SOURCE}"
    else
        log "ERROR: '${app}' failed exact authoritative preflight: ${PRESENT_CHECK_DETAIL}"
        preflight_failed=true
    fi
done
if [[ "${preflight_failed}" == "true" ]]; then
    RUN_SUMMARY="Preflight failed; no uninstall mutation was attempted."
    log "ERROR: Batch preflight failed. No app was mutated."
    exit 1
fi

# Prove that the private evidence destination is writable before the first
# destructive request. The same file is atomically replaced with final state.
RUN_SUMMARY="All targets and versions passed preflight; no mutation has started."
write_evidence "preflight-passed" 0 "${RUN_SUMMARY}"
EVIDENCE_WRITTEN=false

log ""
log "=== Exact Removal Plan ==="
log "Stack: ${SPLUNK_CLOUD_STACK:-unknown}"
log "Search-head target: ${SPLUNK_CLOUD_SEARCH_HEAD:-all search heads}"
scope_suffix=""
USE_LOCAL_SCOPE=false
if cloud_requires_local_scope; then
    scope_suffix=" --scope local"
    USE_LOCAL_SCOPE=true
fi
for index in "${!APP_NAMES[@]}"; do
    log "  $((index + 1)). ${APP_NAMES[$index]} version=${PLAN_VERSIONS[$index]} -> ACS uninstall${scope_suffix}"
done
log "Restart checks: ${RESTART}"
log "REST fallback accepted: ${ACCEPT_REST_FALLBACK}"
log "Evidence file: ${EVIDENCE_FILE}"
if [[ "${ACCEPT_REST_FALLBACK}" == "true" ]]; then
    log "TOPOLOGY RISK ACCEPTED: direct REST DELETE can bypass ACS ownership, desynchronize an SHC, or remove only the contacted member."
fi

if [[ "${ASSUME_YES}" != "true" ]]; then
    if [[ ! -t 0 ]]; then
        RUN_SUMMARY="Destructive plan was not confirmed; no mutation was attempted."
        log "ERROR: Non-interactive uninstall requires --yes after reviewing the exact plan."
        exit 1
    fi
    read -rp "Type 'remove' to execute this exact plan: " confirmation
    if [[ "${confirmation}" != "remove" ]]; then
        RUN_SUMMARY="Operator cancelled the plan; no mutation was attempted."
        log "Cancelled. No app was mutated."
        write_evidence "cancelled" 0 "${RUN_SUMMARY}"
        exit 0
    fi
fi

RUN_SUMMARY="ACS uninstall phase is in progress."
acs_phase_failed=false
for index in "${!APP_NAMES[@]}"; do
    app="${APP_NAMES[$index]}"
    log "Revalidating '${app}' immediately before ACS mutation..."
    if ! check_app_present_exact "${app}" "${PLAN_VERSIONS[$index]}"; then
        ACS_RESULTS[index]="refused-repreflight"
        RECOVERY_ACTIONS[index]="Immediate pre-mutation state/version check failed. Inspect ACS and search-tier state before a new plan."
        log "ERROR: '${app}' changed or became ambiguous after plan confirmation: ${PRESENT_CHECK_DETAIL}"
        log "ERROR: Stopping before the ACS mutation for '${app}' and all later targets."
        acs_phase_failed=true
        break
    fi
    log "Uninstalling '${app}' via ACS..."
    MUTATION_STARTED=true
    set +e
    if [[ "${USE_LOCAL_SCOPE}" == "true" ]]; then
        output="$(acs_command apps uninstall "${app}" --scope local 2>&1)"
    else
        output="$(acs_command apps uninstall "${app}" 2>&1)"
    fi
    rc=$?
    set -e
    if (( rc == 0 )); then
        ACS_RESULTS[index]="accepted"
        RECOVERY_ACTIONS[index]="Await final bounded absence verification."
        log "  ACS accepted '${app}'; this is not completion evidence."
    else
        ACS_RESULTS[index]="failed-rc-${rc}"
        RECOVERY_ACTIONS[index]="ACS failed. Inspect final verification and run 'acs apps describe ${app}' before any retry."
        log "ERROR: ACS uninstall failed for '${app}' (rc=${rc}); stopping additional mutations."
        [[ -n "${output}" ]] && log "  ACS returned diagnostic output; review the ACS audit log for details."
        acs_phase_failed=true
        break
    fi
done

if [[ "${acs_phase_failed}" != "true" && "${RESTART}" == "true" ]]; then
    log "Checking/restarting the stack after ACS uninstall requests..."
    if ! cloud_restart_if_required 900; then
        RUN_SUMMARY="ACS restart/check failed after accepted uninstall requests."
        acs_phase_failed=true
    fi
fi

if refresh_verify_session; then
    REST_AVAILABLE=true
else
    REST_AVAILABLE=false
fi

fallback_candidates=()
verification_failed=false
for index in "${!APP_NAMES[@]}"; do
    app="${APP_NAMES[$index]}"
    if verify_app_absent_bounded "${app}"; then
        FINAL_RESULTS[index]="absent-after-acs (${VERIFY_DETAIL})"
        RECOVERY_ACTIONS[index]="None; bounded verification proved absence."
        log "  VERIFIED ABSENT after ACS: ${app}"
    else
        verify_rc=$?
        FINAL_RESULTS[index]="${VERIFY_STATE}-after-acs (${VERIFY_DETAIL})"
        if [[ "${ACS_RESULTS[$index]}" == "accepted" && "${verify_rc}" -eq 1 ]]; then
            fallback_candidates+=("${index}")
        else
            RECOVERY_ACTIONS[index]="Verification is ambiguous or ACS was not accepted. Inspect 'acs apps describe ${app}' and exact search-tier REST state; do not assume removal."
            verification_failed=true
        fi
    fi
done

rest_mutated=false
if (( ${#fallback_candidates[@]} > 0 )); then
    if [[ "${acs_phase_failed}" == "true" ]]; then
        for index in "${fallback_candidates[@]}"; do
            REST_RESULTS[index]="refused-after-partial-acs-error"
            RECOVERY_ACTIONS[index]="No fallback was attempted after an ACS/restart error. Resolve the partial ACS state and re-verify every target before any further mutation."
        done
        verification_failed=true
    elif [[ "${ACCEPT_REST_FALLBACK}" != "true" ]]; then
        for index in "${fallback_candidates[@]}"; do
            app="${APP_NAMES[$index]}"
            REST_RESULTS[index]="refused-no-explicit-gate"
            RECOVERY_ACTIONS[index]="App remains present. Review ACS/topology ownership; rerun with --accept-rest-fallback --yes only after approving direct-member risk."
            log "ERROR: '${app}' remains present. Direct REST DELETE was not authorized."
        done
        verification_failed=true
    elif [[ "${REST_AVAILABLE}" != "true" ]]; then
        for index in "${fallback_candidates[@]}"; do
            REST_RESULTS[index]="unavailable"
            RECOVERY_ACTIONS[index]="REST fallback was accepted but search-tier authentication is unavailable; inspect ACS/topology state manually."
        done
        verification_failed=true
    else
        log ""
        log "Executing explicitly accepted REST fallback. This may bypass ACS/SHC topology ownership."
        for index in "${fallback_candidates[@]}"; do
            app="${APP_NAMES[$index]}"
            log "  Revalidating '${app}' immediately before direct REST mutation..."
            if ! check_rest_fallback_exact "${app}" "${PLAN_VERSIONS[$index]}"; then
                REST_RESULTS[index]="refused-repreflight"
                RECOVERY_ACTIONS[index]="Immediate REST fallback state/version check failed. Stop and reconcile ACS/search-tier ownership before retrying."
                log "ERROR: REST fallback re-preflight failed for '${app}': ${REST_FALLBACK_CHECK_DETAIL}"
                verification_failed=true
                break
            fi
            REST_DELETE_RESULT=""
            if delete_app_via_rest "${app}"; then
                REST_RESULTS[index]="${REST_DELETE_RESULT}"
                RECOVERY_ACTIONS[index]="Await final bounded absence verification after direct REST fallback."
                rest_mutated=true
                log "  REST fallback request accepted for '${app}' (${REST_DELETE_RESULT})."
            else
                REST_RESULTS[index]="${REST_DELETE_RESULT:-ambiguous}"
                RECOVERY_ACTIONS[index]="REST fallback failed/was ambiguous. Stop; inspect exact app state on every SHC member before retrying."
                log "ERROR: REST fallback failed or was ambiguous for '${app}'; stopping additional fallback mutations."
                verification_failed=true
                break
            fi
        done
        if [[ "${rest_mutated}" == "true" && "${RESTART}" == "true" ]]; then
            log "Checking/restarting the stack after direct REST fallback..."
            if ! cloud_restart_if_required 900; then
                RUN_SUMMARY="ACS restart/check failed after direct REST fallback."
                verification_failed=true
            fi
        fi
    fi
fi

if refresh_verify_session; then
    REST_AVAILABLE=true
else
    REST_AVAILABLE=false
fi

log ""
log "=== Final Bounded Verification ==="
all_absent=true
for index in "${!APP_NAMES[@]}"; do
    app="${APP_NAMES[$index]}"
    if verify_app_absent_bounded "${app}"; then
        FINAL_RESULTS[index]="absent (${VERIFY_DETAIL})"
        if [[ "${ACS_RESULTS[$index]}" == failed-* ]]; then
            RECOVERY_ACTIONS[index]="Absence is proved, but the ACS command failed; review ACS audit state before retrying any unattempted apps."
        else
            RECOVERY_ACTIONS[index]="None; bounded verification proved absence."
        fi
        log "  ${app} = VERIFIED ABSENT"
    else
        verify_rc=$?
        if [[ "${VERIFY_STATE}" == "disagreement" ]]; then
            FINAL_RESULTS[index]="channel-disagreement (${VERIFY_DETAIL})"
            RECOVERY_ACTIONS[index]="ACS and search-tier channels disagree. Treat the app as present and reconcile topology ownership before retrying."
            log "  ${app} = CHANNEL DISAGREEMENT / PRESENT (${VERIFY_DETAIL})"
        elif (( verify_rc == 1 )); then
            FINAL_RESULTS[index]="still-present (${VERIFY_DETAIL})"
            RECOVERY_ACTIONS[index]="App is still present. Inspect ACS operation status and topology ownership before a reviewed retry."
            log "  ${app} = STILL PRESENT (${VERIFY_DETAIL})"
        else
            FINAL_RESULTS[index]="ambiguous (${VERIFY_DETAIL})"
            RECOVERY_ACTIONS[index]="Absence could not be proved. Restore ACS/REST verification and rerun status checks; do not report removal."
            log "  ${app} = VERIFICATION AMBIGUOUS (${VERIFY_DETAIL})"
        fi
        all_absent=false
    fi
done

if [[ "${acs_phase_failed}" == "true" || "${verification_failed}" == "true" || "${all_absent}" != "true" ]]; then
    RUN_SUMMARY="Batch ended with a partial/error state. Consult per-app recovery evidence; no unverified removal is reported as success."
    write_evidence "failed" 1 "${RUN_SUMMARY}"
    exit 1
fi

RUN_SUMMARY="Every requested app passed bounded final absence verification."
write_evidence "succeeded" 0 "${RUN_SUMMARY}"
log "SUCCESS: Every requested app is verified absent."
