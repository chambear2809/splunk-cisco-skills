#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-k8s-frontend-rum-rendered"
LIVE=false
CHECK_INJECTION_URL=""
CHECK_SESSION_REPLAY_URL=""
CHECK_CSP_URL=""
CHECK_RUM_INGEST=false
CHECK_SERVER_TIMING_URL=""
CHECK_SOURCE_MAPS=false
SOURCE_MAP_TARGET_DIR="dist"

usage() {
    cat <<'EOF'
Splunk Observability Kubernetes Frontend RUM validation

Usage:
  bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR              Rendered output directory
  --live                        Allow live HTTP / DNS probes
  --check-injection URL         Curl URL and grep for SplunkRum.init(
  --check-session-replay URL    Same plus SplunkSessionRecorder.init(
  --check-csp URL               Curl HEAD URL, parse Content-Security-Policy
  --check-rum-ingest            DNS + TCP probe of rum-ingest.<realm>.<endpoint-domain>:443
  --check-server-timing URL     Curl HEAD URL, grep for Server-Timing.*traceparent
                                If absent, emits handoff-auto-instrumentation.sh
  --check-source-maps           Run splunk-rum sourcemaps verify --path <dir>
  --source-map-dir DIR          Override the source-map directory (default: dist)
  --help                        Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --check-injection) require_arg "$1" "$#" || exit 1; CHECK_INJECTION_URL="$2"; LIVE=true; shift 2 ;;
        --check-session-replay) require_arg "$1" "$#" || exit 1; CHECK_SESSION_REPLAY_URL="$2"; LIVE=true; shift 2 ;;
        --check-csp) require_arg "$1" "$#" || exit 1; CHECK_CSP_URL="$2"; LIVE=true; shift 2 ;;
        --check-rum-ingest) CHECK_RUM_INGEST=true; LIVE=true; shift ;;
        --check-server-timing) require_arg "$1" "$#" || exit 1; CHECK_SERVER_TIMING_URL="$2"; LIVE=true; shift 2 ;;
        --check-source-maps) CHECK_SOURCE_MAPS=true; shift ;;
        --source-map-dir) require_arg "$1" "$#" || exit 1; SOURCE_MAP_TARGET_DIR="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_file() { [[ -f "$1" ]] || { log "ERROR: Missing $1"; exit 1; }; }

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/preflight-report.md"
check_file "${OUTPUT_DIR}/runbook.md"

# Prefer repo-local venv python.
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)"
fi

log "Static: verifying YAML well-formedness and rendering invariants."
"${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
"""Static validation pass for the rendered RUM injection assets."""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print("ERROR: PyYAML missing; install requirements-agent.txt", file=sys.stderr)
    raise SystemExit(1)

root = Path(sys.argv[1])
errors: list[str] = []
warnings: list[str] = []
metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))


def load_all(path: Path):
    if not path.exists():
        return []
    return [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]


# Every rendered manifest must parse and have a kind/apiVersion.
yaml_files = sorted((root / "k8s-rum").glob("*.yaml"))
for path in yaml_files:
    try:
        docs = load_all(path)
    except yaml.YAMLError as exc:
        errors.append(f"{path}: YAML parse error: {exc}")
        continue
    for doc in docs:
        if not isinstance(doc, dict):
            errors.append(f"{path}: non-mapping document.")
            continue
        if "kind" not in doc or "apiVersion" not in doc:
            errors.append(f"{path}: missing kind / apiVersion.")

# CSP-style invariants on the rendered <script src=> URLs.
http_re = re.compile(r"<script\s+src=\"(http://[^\"]+)\"")
latest_url_re = re.compile(r"o11y-gdi-rum/latest/")
exact_version_re = re.compile(r"o11y-gdi-rum/v\d+\.\d+\.\d+/")
script_with_integrity_re = re.compile(r"<script\s+src=\"[^\"]+\"\s+integrity=\"sha384-[^\"]+\"")
exact_script_re = re.compile(r'<script\s+src="https://[^"]+/o11y-gdi-rum/v\d+\.\d+\.\d+/[^"]+"[^>]*>')
session_replay_init_re = re.compile(r"SplunkSessionRecorder\.init\(")
rum_init_re = re.compile(r"SplunkRum\.init\(")
allow_latest = bool(json.loads((root / "metadata.json").read_text(encoding="utf-8")).get("allow_latest_version"))

# rrweb-legacy options that should not appear when recorder=splunk.
rrweb_legacy_keys = re.compile(r"\b(maskTextSelector|maskInputOptions|maskTextClass|inlineImages|collectFonts)\b")

content_corpus = []
for path in (root / "k8s-rum").glob("*"):
    if path.is_file():
        content_corpus.append((path, path.read_text(encoding="utf-8", errors="replace")))

# https-only
for path, text in content_corpus:
    for m in http_re.finditer(text):
        errors.append(f"{path}: rendered <script src> uses HTTP: {m.group(1)}")

# version-pinned
for path, text in content_corpus:
    if latest_url_re.search(text):
        if metadata.get("agent_version") != "latest":
            errors.append(f"{path}: rendered URL contains o11y-gdi-rum/latest/ but metadata.agent_version is not 'latest'.")

# SRI-emitted advisory
if exact_version_re.search("\n".join(t for _, t in content_corpus)):
    has_integrity = any(script_with_integrity_re.search(t) for _, t in content_corpus)
    has_exact_script = any(exact_script_re.search(t) for _, t in content_corpus)
    if has_exact_script and not has_integrity:
        warnings.append("Exact-version <script src> rendered without an integrity= attribute. "
                        "Operator should fetch the SRI hash and re-render with --agent-sri.")

# rrweb-legacy guard (only when Session Replay is enabled and recorder=splunk)
if metadata.get("session_replay_enabled"):
    for path, text in content_corpus:
        if "SplunkSessionRecorder.init(" in text and "recorder: \"splunk\"" in text:
            for m in rrweb_legacy_keys.finditer(text):
                warnings.append(f"{path}: legacy rrweb option '{m.group(1)}' present alongside recorder=splunk; migrate to sensitivityRules / features.packAssets.")

# Mode A.i nginx config invariants
for path, text in content_corpus:
    if "splunk-rum.conf" in path.name and "ConfigMap" in text:
        if "sub_filter_types text/html;" not in text:
            errors.append(f"{path}: nginx ConfigMap missing 'sub_filter_types text/html;'.")
        if "Accept-Encoding" not in text:
            warnings.append(f"{path}: nginx ConfigMap does not disable Accept-Encoding (gzip will defeat sub_filter on proxied responses).")

# Mode C utility-image guard
for path, text in content_corpus:
    if "initcontainer-patch" in path.name:
        if "splunk-rum-rewriter" in text and "image: " not in text:
            errors.append(f"{path}: initContainer rewriter missing image:.")

# Workload-targeted patches (kind/namespace/name) match metadata.targets.
target_keys = {f"{t['kind']}/{t['namespace']}/{t['name']}" for t in metadata.get("targets") or []}
for path, text in content_corpus:
    if "rum-target-workload" in text:
        for m in re.finditer(r"splunk\.com/rum-target-workload:\s*(\S+)", text):
            if m.group(1) not in target_keys:
                errors.append(f"{path}: target annotation {m.group(1)} not in metadata.targets {sorted(target_keys)}.")

# Realm sanity
SUPPORTED_REALMS = {"us0", "us1", "us2", "eu0", "eu1", "eu2", "au0", "jp0"}
realm = metadata.get("realm") or ""
if realm not in SUPPORTED_REALMS:
    errors.append(f"metadata.json realm={realm!r} not in supported set {sorted(SUPPORTED_REALMS)}.")

# Application name + deployment environment non-empty
if not metadata.get("application_name"):
    errors.append("metadata.json application_name is empty.")
if not metadata.get("deployment_environment"):
    warnings.append("metadata.json deployment_environment is empty (recommended for environment slicing in RUM).")

# Rendered scripts must not echo secrets.
secret_re = re.compile(r"(?i)(rum[_-]?token|access[_-]?token|api[_-]?key)\s*[:=]\s*[A-Za-z0-9._-]{20,}")
for path, text in content_corpus:
    if path.suffix == ".sh":
        for m in secret_re.finditer(text):
            errors.append(f"{path}: rendered script contains what looks like an inline secret: {m.group(0)[:30]}...")

if errors:
    print("Static validation: FAIL")
    for e in errors:
        print(f"  FAIL: {e}")
    if warnings:
        for w in warnings:
            print(f"  WARN: {w}")
    raise SystemExit(2)
else:
    print("Static validation: OK")
    for w in warnings:
        print(f"  WARN: {w}")
PY

# ---------------------------------------------------------------------------
# Live probes (off by default)
# ---------------------------------------------------------------------------

if [[ "${LIVE}" != "true" ]]; then
    log "Static validation passed. Use --live --check-* for live probes."
    exit 0
fi

# Live probes are additive: each one runs and contributes to LIVE_FAIL_COUNT.
# The script exits non-zero at the end only if any probe failed, so an
# operator running --check-injection + --check-csp + --check-rum-ingest gets
# all three results in one pass.
LIVE_FAIL_COUNT=0

# SDK presence markers that are stable across all four injection modes AND
# across every JS bundler / minifier. Listed strongest-signal-first:
#
#   1. The literal init call (modes A.i, A.ii, C, and unminified mode B):
#        SplunkRum.init( | SplunkOtelWeb.init(
#   2. The runtime-config emit signature (mode B from this skill):
#        window.SPLUNK_RUM_CONFIG | window.SPLUNK_RUM_SESSION_REPLAY_CONFIG
#   3. SDK import / package strings (survive minification because they're
#      module exports or string literals embedded in the bundle):
#        @splunk/otel-web | splunk-otel-web | SplunkRum | SplunkOtelWeb
#   4. Splunk RUM endpoint strings (URLs are kept verbatim by minifiers):
#        cdn.observability.splunkcloud.com/o11y-gdi-rum
#        cdn.signalfx.com/o11y-gdi-rum
#        rum-ingest.<realm>.observability.splunkcloud.com
#        rum-ingest.<realm>.signalfx.com
#   5. Splunk RUM session-tracking cookie names emitted by the SDK:
#        __splunk_rum_sid | _splunk_rum_user_anonymousId
#
# `--check-injection` reports the strongest match and exits OK on any of
# them. This covers inline-injected snippets, npm-bundled SDKs (with or
# without minifier renaming), CDN-loaded SDKs, and runtime-config ConfigMap
# delivery indistinguishably from the operator's point of view.

_RUM_INIT_RE='SplunkRum\.init\(|SplunkOtelWeb\.init\('
_RUM_RUNTIME_CONFIG_RE='window\.SPLUNK_RUM_CONFIG|window\.SPLUNK_RUM_SESSION_REPLAY_CONFIG'
_RUM_SDK_RE='@splunk/otel-web|splunk-otel-web|SplunkRum|SplunkOtelWeb'
_RUM_ENDPOINT_RE='o11y-gdi-rum|rum-ingest\.[a-z0-9-]+\.(observability\.splunkcloud\.com|signalfx\.com)'
_RUM_COOKIE_RE='__splunk_rum_sid|_splunk_rum_user_anonymousId'
_SR_INIT_RE='SplunkSessionRecorder\.init\(|window\.SPLUNK_RUM_SESSION_REPLAY_CONFIG'
_SR_SDK_RE='splunk-otel-web-session-recorder|SplunkSessionRecorder'

# Helper: fetch base URL + every linked <script src=...> reference into a
# single tempfile, return the path on stdout. Caller greps the file directly
# (avoids the printf|grep + pipefail SIGPIPE trap on large bodies).
_fetch_html_and_scripts_into() {
    local base_url="$1" outfile="$2"
    : > "${outfile}"
    if ! curl -fsSL "${base_url}" >> "${outfile}" 2>/dev/null; then
        return 1
    fi
    local html
    html="$(cat "${outfile}")"
    local origin
    origin="$(printf '%s' "${base_url}" | sed -E 's#^(https?://[^/]+).*#\1#')"
    local srcs
    srcs="$(printf '%s' "${html}" \
        | grep -oE '<script[^>]+src="[^"]+"' \
        | sed -E 's#.*src="([^"]+)".*#\1#')"
    while IFS= read -r src; do
        [[ -z "${src}" ]] && continue
        local full
        case "${src}" in
            http://*|https://*) full="${src}" ;;
            //*) full="https:${src}" ;;
            /*) full="${origin}${src}" ;;
            *) full="${base_url%/}/${src}" ;;
        esac
        printf '\n/* %s */\n' "${full}" >> "${outfile}"
        curl -fsSL --max-time 15 "${full}" >> "${outfile}" 2>/dev/null || true
    done <<< "${srcs}"
}

# Helper: tiered probe. Tries strong signals first, falls back to weaker
# ones. Reports which tier matched. Returns 0 on any match, 1 on none.
_probe_rum_presence() {
    local base_url="$1" desc="$2"
    local probe_file
    probe_file="$(mktemp -t splunk-rum-probe.XXXXXX)"
    if ! _fetch_html_and_scripts_into "${base_url}" "${probe_file}"; then
        log "  FAIL: ${desc}: cannot fetch ${base_url}"
        rm -f "${probe_file}"
        return 1
    fi
    if [[ -n "${RUM_PROBE_DEBUG:-}" ]]; then
        log "  DEBUG: body bytes=$(wc -c < "${probe_file}") tier1=$(grep -Ec "${_RUM_INIT_RE}" "${probe_file}" || true) tier2=$(grep -Ec "${_RUM_RUNTIME_CONFIG_RE}" "${probe_file}" || true) tier3=$(grep -Ec "${_RUM_SDK_RE}" "${probe_file}" || true) tier4=$(grep -Ec "${_RUM_ENDPOINT_RE}" "${probe_file}" || true)"
    fi
    local rc=1
    if grep -Eq "${_RUM_INIT_RE}" "${probe_file}"; then
        log "  OK: ${desc}: explicit SplunkRum.init( found (inline or unminified bundle)."
        rc=0
    elif grep -Eq "${_RUM_RUNTIME_CONFIG_RE}" "${probe_file}"; then
        log "  OK: ${desc}: runtime-config payload (window.SPLUNK_RUM_CONFIG) found."
        rc=0
    elif grep -Eq "${_RUM_SDK_RE}" "${probe_file}"; then
        log "  OK: ${desc}: SDK identifiers (SplunkRum / @splunk/otel-web) found in served assets (likely minified npm bundle)."
        rc=0
    elif grep -Eq "${_RUM_ENDPOINT_RE}" "${probe_file}"; then
        log "  OK: ${desc}: Splunk RUM endpoint strings (CDN or rum-ingest URL) found in served assets."
        rc=0
    elif grep -Eq "${_RUM_COOKIE_RE}" "${probe_file}"; then
        log "  OK: ${desc}: Splunk RUM session cookie name found in served assets."
        rc=0
    else
        # Final fallback: response CSP says the page is allowed to talk to
        # the RUM ingest endpoint. Strong evidence the site is configured
        # for RUM even when the bundle minified every identifier away.
        local headers
        headers="$(curl -fsSI "${base_url}" 2>/dev/null || true)"
        if printf '%s' "${headers}" | grep -iE '^content-security-policy:' | grep -Eq "${_RUM_ENDPOINT_RE}"; then
            log "  OK: ${desc}: response CSP allow-lists rum-ingest.<realm>.*; site is configured for Splunk RUM (cannot confirm SDK from JS)."
            rc=0
        else
            log "  FAIL: ${desc}: no SplunkRum.init / SDK identifier / endpoint string / RUM session cookie / CSP allow-list match at ${base_url} or in any linked <script src> bundle."
            rc=1
        fi
    fi
    rm -f "${probe_file}"
    return "${rc}"
}

# Same tiered approach for the Session Replay recorder.
_probe_sr_presence() {
    local base_url="$1"
    local probe_file
    probe_file="$(mktemp -t splunk-rum-sr-probe.XXXXXX)"
    if ! _fetch_html_and_scripts_into "${base_url}" "${probe_file}"; then
        log "  FAIL: Session Replay: cannot fetch ${base_url}"
        rm -f "${probe_file}"
        return 1
    fi
    local rc=1
    if grep -Eq "${_SR_INIT_RE}" "${probe_file}"; then
        log "  OK: Session Replay: explicit SplunkSessionRecorder.init( or runtime-config payload found."
        rc=0
    elif grep -Eq "${_SR_SDK_RE}" "${probe_file}"; then
        log "  OK: Session Replay: recorder identifiers found in served assets (likely minified)."
        rc=0
    else
        log "  FAIL: Session Replay: no SplunkSessionRecorder.init / recorder SDK identifier match at ${base_url} or in any linked <script src> bundle."
        rc=1
    fi
    rm -f "${probe_file}"
    return "${rc}"
}

if [[ -n "${CHECK_INJECTION_URL}" ]]; then
    log "--check-injection ${CHECK_INJECTION_URL}"
    _probe_rum_presence "${CHECK_INJECTION_URL}" "RUM injection" \
        || LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
fi

if [[ -n "${CHECK_SESSION_REPLAY_URL}" ]]; then
    log "--check-session-replay ${CHECK_SESSION_REPLAY_URL}"
    _probe_sr_presence "${CHECK_SESSION_REPLAY_URL}" \
        || LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
fi

if [[ -n "${CHECK_CSP_URL}" ]]; then
    log "--check-csp ${CHECK_CSP_URL}"
    csp="$(curl -fsSI "${CHECK_CSP_URL}" 2>/dev/null | grep -i '^content-security-policy:' || true)"
    if [[ -z "${csp}" ]]; then
        log "  WARN: no Content-Security-Policy header on ${CHECK_CSP_URL}; that is permissive but unusual."
    else
        cdn_re='cdn\.(observability\.splunkcloud\.com|signalfx\.com)'
        ingest_re='rum-ingest\.[a-z0-9]+\.(observability\.splunkcloud\.com|signalfx\.com)'
        if printf '%s' "${csp}" | grep -Eq "${cdn_re}"; then
            log "  OK: CSP allows the Splunk RUM CDN."
        elif printf '%s' "${csp}" | grep -Eqi "script-src[^;]*'self'"; then
            log "  WARN: CSP script-src='self' only; that is correct ONLY when the agent is bundled (mode runtime-config / npm). For CDN modes A.i / A.ii / C, add the Splunk RUM CDN host."
        else
            log "  FAIL: CSP missing the Splunk RUM CDN (script-src ${cdn_re}) and not 'self'-only."
            LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
        fi
        if printf '%s' "${csp}" | grep -Eq "${ingest_re}"; then
            log "  OK: CSP allows the Splunk RUM beacon endpoint."
        else
            log "  FAIL: CSP missing the Splunk RUM beacon (connect-src ${ingest_re})"
            LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
        fi
    fi
fi

if [[ "${CHECK_RUM_INGEST}" == "true" ]]; then
    realm="$("${PYTHON_BIN}" -c "import json,sys; print(json.loads(open('${OUTPUT_DIR}/metadata.json').read()).get('realm') or 'us0')")"
    domain="$("${PYTHON_BIN}" -c "import json; print(json.loads(open('${OUTPUT_DIR}/metadata.json').read()).get('endpoint_domain') or 'splunkcloud')")"
    if [[ "${domain}" == "splunkcloud" ]]; then
        host="rum-ingest.${realm}.observability.splunkcloud.com"
    else
        host="rum-ingest.${realm}.signalfx.com"
    fi
    log "--check-rum-ingest ${host}:443"
    if getent hosts "${host}" >/dev/null 2>&1 || host "${host}" >/dev/null 2>&1 \
       || dscacheutil -q host -a name "${host}" 2>/dev/null | grep -q "ip_address"; then
        log "  OK: DNS resolves for ${host}"
    else
        log "  FAIL: DNS does not resolve for ${host}"
        LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
    fi
    if (timeout 5 bash -c "exec 9<>/dev/tcp/${host}/443") 2>/dev/null; then
        log "  OK: TCP 443 reachable on ${host}"
    else
        log "  WARN: TCP 443 not reachable on ${host} from this host (egress firewall may block; browsers may still reach it)."
    fi
fi

if [[ -n "${CHECK_SERVER_TIMING_URL}" ]]; then
    log "--check-server-timing ${CHECK_SERVER_TIMING_URL}"
    headers="$(curl -fsSI "${CHECK_SERVER_TIMING_URL}" 2>/dev/null || true)"
    if printf '%s' "${headers}" | grep -iqE '^server-timing:.*traceparent'; then
        log "  OK: backend emits Server-Timing: traceparent (RUM-to-APM linking will work)."
    else
        log "  FAIL: backend missing Server-Timing: traceparent header. Emitting handoff-auto-instrumentation.sh."
        cat > "${OUTPUT_DIR}/handoff-auto-instrumentation.sh" <<HANDOFF
#!/usr/bin/env bash
# Advisory: backend missing Server-Timing: traceparent header.
# Splunk Browser RUM links to APM via this header on backend HTTP responses.
# Backends instrumented via the Splunk OTel auto-instrumentation operator
# emit it automatically.
#
# Run:
#   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh --help
#
# CORS callers also need:
#   Access-Control-Expose-Headers: Server-Timing
#
# Probe was against: ${CHECK_SERVER_TIMING_URL}
echo 'See skills/splunk-observability-k8s-auto-instrumentation-setup/SKILL.md for backend wiring.'
HANDOFF
        chmod +x "${OUTPUT_DIR}/handoff-auto-instrumentation.sh"
        log "  Wrote ${OUTPUT_DIR}/handoff-auto-instrumentation.sh"
        LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
    fi
fi

if [[ "${CHECK_SOURCE_MAPS}" == "true" ]]; then
    log "--check-source-maps ${SOURCE_MAP_TARGET_DIR}"
    if ! command -v splunk-rum >/dev/null; then
        log "  WARN: splunk-rum CLI not on PATH. Install with: npm install -g @splunk/rum-cli"
    else
        if splunk-rum sourcemaps verify --path "${SOURCE_MAP_TARGET_DIR}"; then
            log "  OK: source maps verified."
        else
            log "  FAIL: splunk-rum sourcemaps verify reported errors."
            LIVE_FAIL_COUNT=$((LIVE_FAIL_COUNT + 1))
        fi
    fi
fi

if [[ "${LIVE_FAIL_COUNT}" -gt 0 ]]; then
    log "${LIVE_FAIL_COUNT} live check(s) FAILED."
    exit 2
fi
log "All requested checks passed."
