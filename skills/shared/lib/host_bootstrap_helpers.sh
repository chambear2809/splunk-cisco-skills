#!/usr/bin/env bash
# Shared helpers for bootstrapping Splunk Enterprise hosts.
# Source this after credential_helpers.sh.

[[ -n "${_HOST_BOOTSTRAP_HELPERS_LOADED:-}" ]] && return 0
_HOST_BOOTSTRAP_HELPERS_LOADED=true

HBS_ENTERPRISE_DOWNLOAD_PAGE_URL="${HBS_ENTERPRISE_DOWNLOAD_PAGE_URL:-https://www.splunk.com/en_us/download/splunk-enterprise.html}"
HBS_UNIVERSAL_FORWARDER_DOWNLOAD_PAGE_URL="${HBS_UNIVERSAL_FORWARDER_DOWNLOAD_PAGE_URL:-https://www.splunk.com/en_us/download/universal-forwarder.html}"
HBS_LATEST_METADATA_MAX_AGE_SECONDS="${HBS_LATEST_METADATA_MAX_AGE_SECONDS:-2592000}"

hbs_is_interactive() {
    [[ -t 0 ]]
}

hbs_bool_is_true() {
    case "${1:-}" in
        1|[Tt][Rr][Uu][Ee]|[Yy]|[Yy][Ee][Ss]|[Oo][Nn])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

hbs_normalize_bool() {
    if hbs_bool_is_true "${1:-}"; then
        printf '%s' "true"
    else
        printf '%s' "false"
    fi
}

hbs_prompt_value() {
    local prompt="$1"
    local default_value="${2:-}"
    local value=""

    if ! hbs_is_interactive; then
        return 1
    fi

    if [[ -n "${default_value}" ]]; then
        read -rp "${prompt} [${default_value}]: " value
        printf '%s' "${value:-${default_value}}"
    else
        read -rp "${prompt}: " value
        printf '%s' "${value}"
    fi
}

hbs_prompt_secret_path() {
    local prompt="$1"
    local value=""

    if ! hbs_is_interactive; then
        return 1
    fi

    read -rp "${prompt}: " value
    printf '%s' "${value}"
}

hbs_resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

hbs_shell_join() {
    local joined=""
    local arg
    for arg in "$@"; do
        printf -v joined '%s%q ' "${joined}" "${arg}"
    done
    printf '%s' "${joined% }"
}

# Returns the unquoted body of the currently-registered trap for the given signal,
# or empty if no trap is registered. Uses `eval` because `trap -p` returns the body
# wrapped in shell-quoted single-quotes; the eval removes that quoting.
#
# SECURITY NOTE: This helper assumes every trap currently in scope was registered by
# repo-controlled code with sanitized arguments. Callers must NOT register traps
# whose body is constructed from untrusted input — the eval here would re-interpret
# any shell metacharacters in such a body.
hbs_trap_body() {
    local signal="${1:-}"
    local trap_output body
    trap_output="$(trap -p "${signal}" || true)"
    [[ -n "${trap_output}" ]] || return 0
    body="${trap_output#trap -- }"
    body="${body%" ${signal}"}"
    eval "printf '%s' ${body}"
}

hbs_append_cleanup_trap() {
    local cleanup_cmd="${1:-}"
    shift || true
    local signal existing
    [[ -n "${cleanup_cmd}" ]] || return 0
    for signal in "$@"; do
        existing="$(hbs_trap_body "${signal}")"
        if [[ -n "${existing}" ]]; then
            # shellcheck disable=SC2064  # intentional: cleanup paths are captured at registration time.
            trap "${existing}; ${cleanup_cmd}" "${signal}"
        else
            # shellcheck disable=SC2064  # intentional: cleanup paths are captured at registration time.
            trap "${cleanup_cmd}" "${signal}"
        fi
    done
}

hbs_detect_package_type() {
    local source_path="${1:-}"
    local lower_name
    lower_name="$(basename "${source_path}" | tr '[:upper:]' '[:lower:]')"
    case "${lower_name}" in
        *.tar.gz|*.tgz) printf '%s' "tgz" ;;
        *.rpm) printf '%s' "rpm" ;;
        *.deb) printf '%s' "deb" ;;
        *.msi) printf '%s' "msi" ;;
        *.dmg) printf '%s' "dmg" ;;
        *.pkg) printf '%s' "pkg" ;;
        *.txz) printf '%s' "txz" ;;
        *.p5p) printf '%s' "p5p" ;;
        *.tar.z|*.z) printf '%s' "tar-z" ;;
        *)
            echo "ERROR: Could not detect package type from '${source_path}'." >&2
            return 1
            ;;
    esac
}

hbs_extract_splunk_package_version() {
    local source_path="${1:-}"
    HBS_PACKAGE_SOURCE="${source_path}" python3 -c '
import os
import re

source = os.environ.get("HBS_PACKAGE_SOURCE", "")
match = re.search(r"splunk(?:forwarder)?-(\d+(?:\.\d+)+)-", os.path.basename(source))
if match:
    print(match.group(1), end="")
'
}

hbs_extract_splunk_version() {
    local raw_text="${1:-}"
    HBS_VERSION_TEXT="${raw_text}" python3 -c '
import os
import re

text = os.environ.get("HBS_VERSION_TEXT", "")
match = re.search(r"(\d+(?:\.\d+)+)", text)
if match:
    print(match.group(1), end="")
'
}

hbs_versions_equal() {
    local left="${1:-}"
    local right="${2:-}"

    [[ -n "${left}" && -n "${right}" ]] || return 1

    python3 - "${left}" "${right}" <<'PY'
import sys

def normalize(raw):
    tokens = [int(token) for token in raw.split(".")]
    while tokens and tokens[-1] == 0:
        tokens.pop()
    return tokens

sys.exit(0 if normalize(sys.argv[1]) == normalize(sys.argv[2]) else 1)
PY
}

hbs_require_enterprise_package_for_role() {
    local package_path="${1:-}"
    local role="${2:-}"
    local lower_name
    lower_name="$(basename "${package_path}" | tr '[:upper:]' '[:lower:]')"

    case "${role}" in
        standalone-search-tier|standalone-indexer|heavy-forwarder|cluster-manager|indexer-peer|shc-deployer|shc-member)
            if [[ "${lower_name}" == *splunkforwarder* || "${lower_name}" == *universalforwarder* ]]; then
                echo "ERROR: Role '${role}' requires a full Splunk Enterprise package, not a Universal Forwarder package." >&2
                echo "Heavy forwarders are full Splunk Enterprise instances with forwarding configuration." >&2
                return 1
            fi
            ;;
    esac
}

hbs_sha256_file() {
    local file_path="${1:-}"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "${file_path}" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "${file_path}" | awk '{print $1}'
    else
        echo "ERROR: Neither sha256sum nor shasum is available for checksum verification." >&2
        return 1
    fi
}

hbs_sha512_file() {
    local file_path="${1:-}"
    if command -v sha512sum >/dev/null 2>&1; then
        sha512sum "${file_path}" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 512 "${file_path}" | awk '{print $1}'
    else
        echo "ERROR: Neither sha512sum nor shasum is available for checksum verification." >&2
        return 1
    fi
}

hbs_verify_checksum() {
    local file_path="${1:-}"
    local expected="${2:-}"
    local actual normalized

    [[ -n "${expected}" ]] || return 0

    normalized="${expected#sha256:}"
    actual="$(hbs_sha256_file "${file_path}")" || return 1

    if [[ "${actual}" != "${normalized}" ]]; then
        echo "ERROR: SHA256 checksum mismatch for ${file_path}." >&2
        echo "Expected: ${normalized}" >&2
        echo "Actual:   ${actual}" >&2
        return 1
    fi
}

hbs_verify_sha512_checksum() {
    local file_path="${1:-}"
    local expected="${2:-}"
    local actual normalized

    [[ -n "${expected}" ]] || {
        echo "ERROR: Expected SHA512 value is required for ${file_path}." >&2
        return 1
    }

    normalized="${expected#sha512:}"
    actual="$(hbs_sha512_file "${file_path}")" || return 1

    if [[ "${actual}" != "${normalized}" ]]; then
        echo "ERROR: SHA512 checksum mismatch for ${file_path}." >&2
        echo "Expected: ${normalized}" >&2
        echo "Actual:   ${actual}" >&2
        return 1
    fi
}

hbs_build_cached_download_path() {
    local cache_dir="${1:-}"
    local source_url="${2:-}"
    python3 - "${cache_dir}" "${source_url}" <<'PY'
from pathlib import Path
from urllib.parse import urlparse
import sys

cache_dir = Path(sys.argv[1]).resolve()
raw_url = sys.argv[2]
parsed = urlparse(raw_url)
name = Path(parsed.path).name or "splunk-package.bin"
print(cache_dir / name, end="")
PY
}

hbs_latest_enterprise_metadata_path() {
    local cache_dir="${1:-}"
    local package_type="${2:-}"
    python3 - "${cache_dir}" "${package_type}" <<'PY'
from pathlib import Path
import sys

cache_dir = Path(sys.argv[1]).resolve()
package_type = sys.argv[2]
print(cache_dir / f".latest-splunk-enterprise-{package_type}.json", end="")
PY
}

hbs_latest_universal_forwarder_metadata_path() {
    local cache_dir="${1:-}"
    local target_os="${2:-}"
    local target_arch="${3:-}"
    local package_type="${4:-}"
    python3 - "${cache_dir}" "${target_os}" "${target_arch}" "${package_type}" <<'PY'
from pathlib import Path
import re
import sys

cache_dir = Path(sys.argv[1]).resolve()
target_os = re.sub(r"[^A-Za-z0-9_.-]+", "-", sys.argv[2]).strip("-").lower()
target_arch = re.sub(r"[^A-Za-z0-9_.-]+", "-", sys.argv[3]).strip("-").lower()
package_type = re.sub(r"[^A-Za-z0-9_.-]+", "-", sys.argv[4]).strip("-").lower()
print(cache_dir / f".latest-splunk-universal-forwarder-{target_os}-{target_arch}-{package_type}.json", end="")
PY
}

hbs_latest_enterprise_metadata_field() {
    local metadata_json="${1:-}"
    local field_name="${2:-}"
    HBS_METADATA_JSON="${metadata_json}" python3 -c '
import json
import os
import sys

data = json.loads(os.environ["HBS_METADATA_JSON"])
value = data[sys.argv[1]]
if isinstance(value, str):
    print(value, end="")
else:
    print(json.dumps(value, sort_keys=True), end="")
' "${field_name}"
}

hbs_latest_enterprise_metadata_with_sha512() {
    local metadata_json="${1:-}"
    local sha512_value="${2:-}"
    HBS_METADATA_JSON="${metadata_json}" HBS_METADATA_SHA512="${sha512_value}" python3 -c '
import json
import os

data = json.loads(os.environ["HBS_METADATA_JSON"])
data["sha512"] = os.environ["HBS_METADATA_SHA512"]
print(json.dumps(data, sort_keys=True), end="")
'
}

hbs_write_latest_enterprise_metadata_cache() {
    local cache_dir="${1:-}"
    local package_type="${2:-}"
    local metadata_json="${3:-}"
    local metadata_path tmp_file

    metadata_path="$(hbs_latest_enterprise_metadata_path "${cache_dir}" "${package_type}")"
    tmp_file="$(mktemp)"

    if ! HBS_METADATA_JSON="${metadata_json}" python3 -c '
from pathlib import Path
import json
import os
import sys
import time

path = Path(sys.argv[1])
data = json.loads(os.environ["HBS_METADATA_JSON"])
required = [
    "package_type",
    "package_url",
    "sha512",
    "sha512_url",
    "source_page_url",
    "version",
]
missing = [key for key in required if not data.get(key)]
if missing:
    raise SystemExit(1)
now = int(time.time())
data["cached_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
data["cached_at_epoch"] = now
path.parent.mkdir(parents=True, exist_ok=True)
Path(sys.argv[2]).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
' "${metadata_path}" "${tmp_file}"; then
        rm -f "${tmp_file}"
        echo "ERROR: Failed to write latest Splunk Enterprise metadata cache ${metadata_path}." >&2
        return 1
    fi

    mv -f "${tmp_file}" "${metadata_path}"
}

hbs_read_latest_enterprise_metadata_cache() {
    local cache_dir="${1:-}"
    local package_type="${2:-}"
    local max_age_seconds="${3:-${HBS_LATEST_METADATA_MAX_AGE_SECONDS}}"
    local metadata_path

    metadata_path="$(hbs_latest_enterprise_metadata_path "${cache_dir}" "${package_type}")"
    python3 - "${metadata_path}" "${max_age_seconds}" <<'PY'
from pathlib import Path
import json
import sys
import time

path = Path(sys.argv[1])
max_age_seconds = int(sys.argv[2])
if not path.is_file():
    raise SystemExit(1)

data = json.loads(path.read_text(encoding="utf-8"))
required = [
    "cached_at_epoch",
    "package_type",
    "package_url",
    "sha512",
    "sha512_url",
    "source_page_url",
    "version",
]
if any(not data.get(key) for key in required):
    raise SystemExit(1)

age_seconds = int(time.time()) - int(data["cached_at_epoch"])
if age_seconds > max_age_seconds:
    raise SystemExit(2)

print(json.dumps(data, sort_keys=True), end="")
PY
}

hbs_write_latest_universal_forwarder_metadata_cache() {
    local cache_dir="${1:-}"
    local target_os="${2:-}"
    local target_arch="${3:-}"
    local package_type="${4:-}"
    local metadata_json="${5:-}"
    local metadata_path tmp_file

    metadata_path="$(hbs_latest_universal_forwarder_metadata_path "${cache_dir}" "${target_os}" "${target_arch}" "${package_type}")"
    tmp_file="$(mktemp)"

    if ! HBS_METADATA_JSON="${metadata_json}" python3 -c '
from pathlib import Path
import json
import os
import sys
import time

path = Path(sys.argv[1])
data = json.loads(os.environ["HBS_METADATA_JSON"])
required = [
    "filename",
    "package_type",
    "package_url",
    "sha512",
    "sha512_url",
    "source_page_url",
    "target_arch",
    "target_os",
    "version",
]
missing = [key for key in required if not data.get(key)]
if missing:
    raise SystemExit(1)
now = int(time.time())
data["cached_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
data["cached_at_epoch"] = now
path.parent.mkdir(parents=True, exist_ok=True)
Path(sys.argv[2]).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
' "${metadata_path}" "${tmp_file}"; then
        rm -f "${tmp_file}"
        echo "ERROR: Failed to write latest Splunk Universal Forwarder metadata cache ${metadata_path}." >&2
        return 1
    fi

    mv -f "${tmp_file}" "${metadata_path}"
}

hbs_read_latest_universal_forwarder_metadata_cache() {
    local cache_dir="${1:-}"
    local target_os="${2:-}"
    local target_arch="${3:-}"
    local package_type="${4:-}"
    local max_age_seconds="${5:-${HBS_LATEST_METADATA_MAX_AGE_SECONDS}}"
    local metadata_path

    metadata_path="$(hbs_latest_universal_forwarder_metadata_path "${cache_dir}" "${target_os}" "${target_arch}" "${package_type}")"
    python3 - "${metadata_path}" "${max_age_seconds}" <<'PY'
from pathlib import Path
import json
import sys
import time

path = Path(sys.argv[1])
max_age_seconds = int(sys.argv[2])
if not path.is_file():
    raise SystemExit(1)

data = json.loads(path.read_text(encoding="utf-8"))
required = [
    "cached_at_epoch",
    "filename",
    "package_type",
    "package_url",
    "sha512",
    "sha512_url",
    "source_page_url",
    "target_arch",
    "target_os",
    "version",
]
if any(not data.get(key) for key in required):
    raise SystemExit(1)

age_seconds = int(time.time()) - int(data["cached_at_epoch"])
if age_seconds > max_age_seconds:
    raise SystemExit(2)

print(json.dumps(data, sort_keys=True), end="")
PY
}

hbs_prepare_download_curl_args() {
    local max_time="${1:-600}"

    _set_app_download_curl_tls_args || return 1
    _hbs_download_curl_args=(-sSLf --retry 3 --retry-delay 1 --connect-timeout 15 --max-time "${max_time}")
    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_app_download_curl_tls_args.
    if [[ ${#_tls_verify_args[@]} -gt 0 ]]; then
        _hbs_download_curl_args+=("${_tls_verify_args[@]}")
    fi
}

hbs_curl_config_escape() {
    local value="${1:-}"

    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    printf '%s' "${value}"
}

hbs_make_curl_auth_config() {
    local username="${1:-}"
    local password="${2:-}"
    local auth_config

    auth_config="$(mktemp)"
    chmod 600 "${auth_config}"
    printf 'user = "%s:%s"\n' "$(hbs_curl_config_escape "${username}")" "$(hbs_curl_config_escape "${password}")" > "${auth_config}"
    printf '%s' "${auth_config}"
}

hbs_fetch_url_text() {
    local url="${1:-}"
    local username="${2:-}"
    local password="${3:-}"
    local auth_config="" page_text

    [[ -n "${url}" ]] || {
        echo "ERROR: Download URL is required." >&2
        return 1
    }

    hbs_prepare_download_curl_args 180 || return 1
    if [[ -n "${username}" || -n "${password}" ]]; then
        auth_config="$(hbs_make_curl_auth_config "${username}" "${password}")"
        _hbs_download_curl_args+=(-K "${auth_config}")
    fi

    page_text="$(curl "${_hbs_download_curl_args[@]}" "${url}" 2>/dev/null)" || {
        rm -f "${auth_config}"
        echo "ERROR: Failed to fetch ${url}." >&2
        return 1
    }
    rm -f "${auth_config}"

    printf '%s' "${page_text}"
}

hbs_parse_checksum_text() {
    local checksum_text="${1:-}"
    HBS_CHECKSUM_TEXT="${checksum_text}" python3 -c '
import os
import re

text = os.environ["HBS_CHECKSUM_TEXT"]
match = re.search(r"\b([A-Fa-f0-9]{128})\b", text)
if not match:
    raise SystemExit(1)
print(match.group(1).lower(), end="")
'
}

hbs_fetch_expected_sha512() {
    local checksum_url="${1:-}"
    local username="${2:-}"
    local password="${3:-}"
    local checksum_text

    checksum_text="$(hbs_fetch_url_text "${checksum_url}" "${username}" "${password}")" || {
        echo "ERROR: Failed to fetch the official SHA512 from ${checksum_url}." >&2
        return 1
    }

    hbs_parse_checksum_text "${checksum_text}" || {
        echo "ERROR: Failed to parse an official SHA512 checksum from ${checksum_url}." >&2
        return 1
    }
}

hbs_read_target_os_release() {
    local execution_mode="${1:-local}"
    local os_release_path="${HBS_OS_RELEASE_PATH:-/etc/os-release}"

    if [[ "${execution_mode}" == "local" ]]; then
        [[ -f "${os_release_path}" ]] || return 1
        cat "${os_release_path}"
        return 0
    fi

    hbs_capture_target_cmd "${execution_mode}" "$(hbs_shell_join cat /etc/os-release)"
}

hbs_preferred_latest_package_type() {
    local execution_mode="${1:-local}"
    local os_release_text

    if ! os_release_text="$(hbs_read_target_os_release "${execution_mode}" 2>/dev/null)"; then
        printf '%s' "tgz"
        return 0
    fi

    HBS_OS_RELEASE_TEXT="${os_release_text}" python3 -c '
import os

def parse_os_release(text):
    values = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"").strip(chr(39))
        values[key] = value
    return values

values = parse_os_release(os.environ["HBS_OS_RELEASE_TEXT"])
tokens = []
for field_name in ("ID", "ID_LIKE"):
    raw_value = values.get(field_name, "")
    if raw_value:
        tokens.extend(raw_value.lower().split())

token_set = set(tokens)
if token_set & {"debian", "ubuntu"}:
    print("deb", end="")
elif token_set & {"alma", "almalinux", "amzn", "amazon", "centos", "fedora", "ol", "oracle", "opensuse", "opensuse-leap", "rhel", "rocky", "sles", "suse"}:
    print("rpm", end="")
else:
    print("tgz", end="")
'
}

hbs_resolve_latest_enterprise_download_metadata() {
    local package_type="${1:-tgz}"
    local page_url="${2:-${HBS_ENTERPRISE_DOWNLOAD_PAGE_URL}}"
    local page_text metadata

    case "${package_type}" in
        tgz|rpm|deb) ;;
        *)
            echo "ERROR: Unsupported package type '${package_type}' for latest Splunk Enterprise resolution." >&2
            return 1
            ;;
    esac

    page_text="$(hbs_fetch_url_text "${page_url}")" || {
        echo "ERROR: Failed to fetch Splunk Enterprise download page ${page_url}." >&2
        return 1
    }

    metadata="$(printf '%s' "${page_text}" | python3 -c '
import html
import json
import re
import sys

package_type = sys.argv[1]
page_url = sys.argv[2]
text = html.unescape(sys.stdin.read())

pattern_by_type = {
    "tgz": r"https://download\.splunk\.com/products/splunk/releases/(?P<version>[^/]+)/linux/(?P<filename>splunk-[^\"\s<>]+?\.tgz)",
    "deb": r"https://download\.splunk\.com/products/splunk/releases/(?P<version>[^/]+)/linux/(?P<filename>splunk-[^\"\s<>]+?\.deb)",
    "rpm": r"https://download\.splunk\.com/products/splunk/releases/(?P<version>[^/]+)/linux/(?P<filename>splunk-[^\"\s<>]+?\.x86_64\.rpm)",
}
wget_url_pattern_by_type = {
    "tgz": r"https://download\.splunk\.com/products/splunk/releases/[^/]+/linux/splunk-[^\"\s<>]+?\.tgz",
    "deb": r"https://download\.splunk\.com/products/splunk/releases/[^/]+/linux/splunk-[^\"\s<>]+?\.deb",
    "rpm": r"https://download\.splunk\.com/products/splunk/releases/[^/]+/linux/splunk-[^\"\s<>]+?\.x86_64\.rpm",
}
button_pattern = re.compile(
    r"<a\b[^>]*data-link=\"(?P<package_url>"
    + wget_url_pattern_by_type[package_type]
    + r")\"[^>]*data-sha512=\"(?P<sha_url>https://download\.splunk\.com/products/splunk/releases/[^/]+/linux/[^\"\s<>]*sha512[^\"\s<>]*)\"[^>]*data-version=\"(?P<data_version>\d+(?:\.\d+)+)\"[^>]*>",
    re.IGNORECASE,
)
linux_package_pattern = re.compile(
    r"https://download\.splunk\.com/products/splunk/releases/[^/]+/linux/splunk-[^\"\s<>]+?(?:\.tgz|\.deb|\.x86_64\.rpm)"
)
package_pattern = re.compile(pattern_by_type[package_type])
wget_pattern = re.compile(
    r"wget\s+-O\s+(?P<filename>splunk-[^\"\s<>]+)\s+\"(?P<url>" + wget_url_pattern_by_type[package_type] + r")\"",
    re.IGNORECASE,
)
sha_pattern = re.compile(
    r"https://download\.splunk\.com/products/splunk/releases/(?P<version>[^/]+)/linux/(?P<filename>[^\"\s<>]*sha512[^\"\s<>]*)"
)

def version_key(raw_version):
    return tuple(int(token) for token in raw_version.split("."))

def extract_filename_version(filename):
    match = re.match(r"splunk-(\d+(?:\.\d+)+)-", filename)
    return match.group(1) if match else None

page_versions = sorted(set(re.findall(r"Splunk Enterprise\s+(\d+(?:\.\d+)+)", text)), key=version_key)
if len(page_versions) != 1:
    raise SystemExit(1)
page_version = page_versions[0]

wget_entries = {}
for match in wget_pattern.finditer(text):
    wget_entries[match.group("url")] = match.group("filename")

sha_matches = list(sha_pattern.finditer(text))
linux_package_positions = [match.start() for match in linux_package_pattern.finditer(text)]

def sha_match_for(package_url, package_filename, version, position):
    exact = [match for match in sha_matches if package_filename in match.group("filename") and match.group("version") == version]
    if len(exact) == 1:
        return exact[0]

    next_position = len(text)
    for package_position in linux_package_positions:
        if package_position > position:
            next_position = package_position
            break

    nearby = [
        match
        for match in sha_matches
        if match.group("version") == version and position < match.start() < next_position
    ]
    if len(nearby) == 1:
        return nearby[0]
    return None

candidates = {}
for match in button_pattern.finditer(text):
    package_url = match.group("package_url")
    sha_url = match.group("sha_url")
    data_version = match.group("data_version")
    package_version_match = re.search(r"/releases/([^/]+)/linux/", package_url)
    sha_version_match = re.search(r"/releases/([^/]+)/linux/", sha_url)
    if package_version_match is None or sha_version_match is None:
        continue
    package_version = package_version_match.group(1)
    sha_version = sha_version_match.group(1)
    filename = package_url.rsplit("/", 1)[-1]
    filename_version = extract_filename_version(filename)
    if package_version != page_version or data_version != page_version or sha_version != page_version or filename_version != page_version:
        continue
    candidates[package_url] = {
        "package_type": package_type,
        "package_url": package_url,
        "sha512_url": sha_url,
        "source_page_url": page_url,
        "version": package_version,
    }

for match in package_pattern.finditer(text):
    url = match.group(0)
    version = match.group("version")
    filename = match.group("filename")
    wget_filename = wget_entries.get(url)
    sha_match = sha_match_for(url, filename, version, match.start())
    filename_version = extract_filename_version(filename)
    wget_version = extract_filename_version(wget_filename) if wget_filename else None
    if version != page_version or filename_version != version or wget_version != version or sha_match is None or sha_match.group("version") != version:
        continue
    candidates[url] = {
        "package_type": package_type,
        "package_url": url,
        "sha512_url": sha_match.group(0),
        "source_page_url": page_url,
        "version": version,
    }

if not candidates:
    sys.exit(1)

ordered = sorted(candidates.values(), key=lambda item: version_key(item["version"]), reverse=True)
best_version = ordered[0]["version"]
best = [item for item in ordered if item["version"] == best_version]
if len(best) != 1:
    sys.exit(1)

print(json.dumps(best[0], sort_keys=True), end="")
' "${package_type}" "${page_url}" 2>/dev/null)" || {
        echo "ERROR: Failed to parse the latest Splunk Enterprise ${package_type} download URL from ${page_url}." >&2
        return 1
    }

    if [[ -z "${metadata}" ]]; then
        echo "ERROR: Latest Splunk Enterprise metadata was incomplete for package type ${package_type}." >&2
        return 1
    fi

    printf '%s' "${metadata}"
}

hbs_resolve_latest_enterprise_download_url() {
    local metadata_json="${1:-}"
    local version url

    if [[ -n "${metadata_json}" && "${metadata_json}" == \{* ]]; then
        version="$(hbs_latest_enterprise_metadata_field "${metadata_json}" "version")"
        url="$(hbs_latest_enterprise_metadata_field "${metadata_json}" "package_url")"
        printf '%s\t%s' "${version}" "${url}"
        return 0
    fi

    metadata_json="$(hbs_resolve_latest_enterprise_download_metadata "${1:-tgz}" "${2:-${HBS_ENTERPRISE_DOWNLOAD_PAGE_URL}}")" || return 1
    version="$(hbs_latest_enterprise_metadata_field "${metadata_json}" "version")"
    url="$(hbs_latest_enterprise_metadata_field "${metadata_json}" "package_url")"
    printf '%s\t%s' "${version}" "${url}"
}

hbs_normalize_universal_forwarder_package_type() {
    local package_type="${1:-auto}"
    case "${package_type}" in
        tar.Z|tar.z|z|Z) printf '%s' "tar-z" ;;
        tar-gz|tar.gz) printf '%s' "tgz" ;;
        *) printf '%s' "${package_type}" ;;
    esac
}

hbs_resolve_latest_universal_forwarder_download_metadata() {
    local target_os="${1:-linux}"
    local target_arch="${2:-auto}"
    local package_type="${3:-tgz}"
    local page_url="${4:-${HBS_UNIVERSAL_FORWARDER_DOWNLOAD_PAGE_URL}}"
    local page_text metadata normalized_package_type

    normalized_package_type="$(hbs_normalize_universal_forwarder_package_type "${package_type}")"
    case "${target_os}" in
        auto|linux|macos|osx|darwin|windows|freebsd|solaris|aix) ;;
        *)
            echo "ERROR: Unsupported target OS '${target_os}' for latest Splunk Universal Forwarder resolution." >&2
            return 1
            ;;
    esac
    case "${normalized_package_type}" in
        auto|tgz|rpm|deb|msi|dmg|pkg|txz|p5p|tar-z) ;;
        *)
            echo "ERROR: Unsupported package type '${package_type}' for latest Splunk Universal Forwarder resolution." >&2
            return 1
            ;;
    esac

    page_text="$(hbs_fetch_url_text "${page_url}")" || {
        echo "ERROR: Failed to fetch Splunk Universal Forwarder download page ${page_url}." >&2
        return 1
    }

    metadata="$(HBS_UF_PAGE_TEXT="${page_text}" python3 - "${target_os}" "${target_arch}" "${normalized_package_type}" "${page_url}" <<'PY'
import html
import json
import os
import re
import sys
from pathlib import PurePosixPath
from urllib.parse import urlparse


TARGET_OS_RAW = sys.argv[1].lower()
TARGET_ARCH_RAW = sys.argv[2].lower()
PACKAGE_TYPE_RAW = sys.argv[3].lower()
PAGE_URL = sys.argv[4]
TEXT = html.unescape(os.environ["HBS_UF_PAGE_TEXT"])


def version_key(raw_version):
    return tuple(int(token) for token in raw_version.split("."))


def normalize_os(value):
    aliases = {
        "auto": "auto",
        "darwin": "macos",
        "mac": "macos",
        "macos": "macos",
        "osx": "macos",
        "windows": "windows",
        "win": "windows",
        "linux": "linux",
        "freebsd": "freebsd",
        "solaris": "solaris",
        "sunos": "solaris",
        "aix": "aix",
    }
    return aliases.get((value or "").lower(), value.lower())


def normalize_package_type(value):
    value = (value or "").lower().lstrip(".")
    aliases = {
        "auto": "auto",
        "tar.gz": "tgz",
        "tar-gz": "tgz",
        "z": "tar-z",
        "tar.z": "tar-z",
        "tar-z": "tar-z",
    }
    return aliases.get(value, value)


def normalize_arch(value, target_os):
    value = (value or "auto").lower().replace("_", "-")
    if value in {"", "auto"}:
        return "auto"
    if target_os == "windows":
        return {
            "amd64": "x64",
            "x86-64": "x64",
            "x86_64": "x64",
            "x64": "x64",
            "i386": "x86",
            "i686": "x86",
            "386": "x86",
            "x86": "x86",
        }.get(value, value)
    if target_os == "linux":
        return {
            "x64": "amd64",
            "x86-64": "amd64",
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "arm64": "arm64",
            "ppc64le": "ppc64le",
            "s390x": "s390x",
        }.get(value, value)
    if target_os == "macos":
        return {
            "x64": "intel",
            "x86-64": "intel",
            "x86_64": "intel",
            "amd64": "intel",
            "intel": "intel",
            "arm64": "universal2",
            "aarch64": "universal2",
            "m1": "universal2",
            "m2": "universal2",
            "m3": "universal2",
            "universal": "universal2",
            "universal2": "universal2",
        }.get(value, value)
    if target_os == "freebsd":
        if value in {"amd64", "x64", "x86-64", "x86_64"}:
            return "freebsd14-amd64"
        return value
    if target_os == "solaris":
        if value in {"x64", "x86-64", "x86_64"}:
            return "amd64"
        return value
    if target_os == "aix":
        return {"ppc": "powerpc", "ppc64": "powerpc"}.get(value, value)
    return value


def default_arch(target_os):
    return {
        "windows": "x64",
        "linux": "amd64",
        "macos": "universal2",
        "freebsd": "freebsd14-amd64",
        "solaris": "amd64",
        "aix": "powerpc",
    }.get(target_os, "amd64")


def infer_os(url_platform):
    value = normalize_os(url_platform)
    if value == "osx":
        return "macos"
    return value


def infer_package_type(filename):
    lower = filename.lower()
    if lower.endswith((".tar.gz", ".tgz")):
        return "tgz"
    if lower.endswith(".tar.z") or lower.endswith(".z"):
        return "tar-z"
    for suffix in ("rpm", "deb", "msi", "dmg", "pkg", "txz", "p5p"):
        if lower.endswith("." + suffix):
            return suffix
    return ""


def filename_version(filename):
    match = re.search(r"splunkforwarder-(\d+(?:\.\d+)+)-", filename)
    return match.group(1) if match else ""


def infer_arch(filename, target_os, package_type, data_arch=""):
    lower = filename.lower()
    if target_os == "windows":
        if "windows-x86." in lower:
            return "x86"
        if "windows-x64." in lower:
            return "x64"
        return normalize_arch(data_arch, target_os)
    if target_os == "linux":
        if "s390x" in lower:
            return "s390x"
        if "ppc64le" in lower:
            return "ppc64le"
        if "arm64" in lower or "aarch64" in lower:
            return "arm64"
        if "amd64" in lower or "x86_64" in lower:
            return "amd64"
        return normalize_arch(data_arch, target_os)
    if target_os == "macos":
        if "universal2" in lower:
            return "universal2"
        if "intel" in lower:
            return "intel"
        return normalize_arch(data_arch, target_os)
    if target_os == "freebsd":
        match = re.search(r"freebsd(?P<major>\d+)-(?P<arch>[a-z0-9_ -]+?)\.(?:tgz|txz)$", lower)
        if match:
            return f"freebsd{match.group('major')}-{normalize_arch(match.group('arch'), 'linux')}"
        return normalize_arch(data_arch, target_os)
    if target_os == "solaris":
        if "solaris-sparc" in lower:
            return "sparc"
        if "solaris-amd64" in lower:
            return "amd64"
        return normalize_arch(data_arch, target_os)
    if target_os == "aix":
        if "aix-powerpc" in lower:
            return "powerpc"
        return normalize_arch(data_arch, target_os)
    return normalize_arch(data_arch, target_os)


def apply_metadata(target_os, package_type):
    if target_os == "linux" and package_type in {"tgz", "rpm", "deb"}:
        return "local-ssh"
    if target_os == "macos" and package_type == "tgz":
        return "local-ssh"
    if target_os == "macos" and package_type == "dmg":
        return "download-only"
    if target_os == "windows" and package_type == "msi":
        return "render-only"
    return "unsupported-v1"


def parse_attrs(tag):
    return {
        name.lower(): html.unescape(value)
        for name, value in re.findall(r'([A-Za-z0-9_-]+)="([^"]*)"', tag)
    }


def url_parts(url):
    parsed = urlparse(url)
    parts = PurePosixPath(parsed.path).parts
    try:
        release_index = parts.index("releases")
        version = parts[release_index + 1]
        platform = parts[release_index + 2]
    except (ValueError, IndexError):
        return "", "", PurePosixPath(parsed.path).name
    return version, platform, PurePosixPath(parsed.path).name


explicit_page_versions = sorted(
    set(re.findall(r"Splunk Universal Forwarder\s+(\d+(?:\.\d+)+)", TEXT)),
    key=version_key,
)
release_versions = sorted(
    set(re.findall(r"/products/universalforwarder/releases/(\d+(?:\.\d)+)/", TEXT)),
    key=version_key,
)
if explicit_page_versions:
    page_version = explicit_page_versions[-1]
elif release_versions:
    page_version = release_versions[-1]
else:
    raise SystemExit(1)

raw_candidates = []
for tag in re.findall(r"<a\b[^>]*>", TEXT, flags=re.IGNORECASE | re.DOTALL):
    attrs = parse_attrs(tag)
    package_url = attrs.get("data-link", "")
    sha512_url = attrs.get("data-sha512", "")
    data_version = attrs.get("data-version", "")
    if "/products/universalforwarder/releases/" not in package_url:
        continue
    if not sha512_url:
        continue
    version, platform, filename = url_parts(package_url)
    if not filename or filename.endswith((".sha512", ".md5", ".sig")):
        continue
    package_type = infer_package_type(filename)
    target_os = infer_os(platform)
    target_arch = infer_arch(filename, target_os, package_type, attrs.get("data-arch", ""))
    raw_candidates.append(
        {
            "filename": filename,
            "package_type": package_type,
            "package_url": package_url,
            "sha512_url": sha512_url,
            "source_page_url": PAGE_URL,
            "target_arch": target_arch,
            "target_os": target_os,
            "url_platform": platform,
            "version": version,
            "data_version": data_version,
            "v1_apply": apply_metadata(target_os, package_type),
        }
    )

if not raw_candidates:
    url_pattern = re.compile(
        r"https://download\.splunk\.com/products/universalforwarder/releases/"
        r"(?P<version>\d+(?:\.\d)+)/(?P<platform>[^/\s\"'<>]+)/"
        r"(?P<filename>splunkforwarder-[^\s\"'<>]+?\.(?:tgz|tar\.gz|rpm|deb|msi|dmg|pkg|txz|p5p|tar\.Z|Z))",
        flags=re.IGNORECASE,
    )
    seen_urls = set()
    for match in url_pattern.finditer(TEXT):
        package_url = match.group(0)
        if package_url in seen_urls or package_url.endswith((".sha512", ".md5", ".sig")):
            continue
        seen_urls.add(package_url)
        version = match.group("version")
        platform = match.group("platform")
        filename = match.group("filename")
        package_type = infer_package_type(filename)
        target_os = infer_os(platform)
        target_arch = infer_arch(filename, target_os, package_type)
        raw_candidates.append(
            {
                "filename": filename,
                "package_type": package_type,
                "package_url": package_url,
                "sha512_url": f"{package_url}.sha512",
                "source_page_url": PAGE_URL,
                "target_arch": target_arch,
                "target_os": target_os,
                "url_platform": platform,
                "version": version,
                "data_version": version,
                "v1_apply": apply_metadata(target_os, package_type),
            }
        )

candidates = []
for item in raw_candidates:
    version = item["version"]
    filename = item["filename"]
    if version != page_version:
        continue
    if item.get("data_version") and item["data_version"] != page_version:
        continue
    if filename_version(filename) != version:
        continue
    candidates.append(item)

target_os = normalize_os(TARGET_OS_RAW)
if target_os == "auto":
    target_os = "linux"
package_type = normalize_package_type(PACKAGE_TYPE_RAW)
if package_type == "auto":
    package_type = {
        "linux": "tgz",
        "macos": "tgz",
        "windows": "msi",
        "freebsd": "tgz",
        "solaris": "tar-z",
        "aix": "tgz",
    }.get(target_os, "tgz")
target_arch = normalize_arch(TARGET_ARCH_RAW, target_os)
if target_arch == "auto":
    target_arch = default_arch(target_os)

def arch_score(item):
    arch = item["target_arch"]
    if arch == target_arch:
        return 0
    if target_os == "freebsd" and target_arch == "amd64" and arch.endswith("-amd64"):
        return 1
    return 99

def platform_major(item):
    match = re.search(r"freebsd(\d+)-", item["target_arch"])
    if match:
        return int(match.group(1))
    return 0

matches = [
    item
    for item in candidates
    if item["target_os"] == target_os
    and item["package_type"] == package_type
    and arch_score(item) < 99
]
matches = sorted(
    matches,
    key=lambda item: (version_key(item["version"]), -arch_score(item), platform_major(item)),
    reverse=True,
)
if not matches:
    raise SystemExit(1)

best = matches[0]
best_score = arch_score(best)
same_rank = [
    item
    for item in matches
    if version_key(item["version"]) == version_key(best["version"])
    and item["target_os"] == best["target_os"]
    and item["package_type"] == best["package_type"]
    and arch_score(item) == best_score
    and platform_major(item) == platform_major(best)
]
if len({item["package_url"] for item in same_rank}) != 1:
    raise SystemExit(1)

best = dict(best)
best["requested_target_os"] = target_os
best["requested_target_arch"] = target_arch
best["requested_package_type"] = package_type
print(json.dumps(best, sort_keys=True), end="")
PY
)" || {
        echo "ERROR: Failed to parse the latest Splunk Universal Forwarder ${target_os}/${target_arch}/${normalized_package_type} download URL from ${page_url}." >&2
        return 1
    }

    if [[ -z "${metadata}" ]]; then
        echo "ERROR: Latest Splunk Universal Forwarder metadata was incomplete for ${target_os}/${target_arch}/${normalized_package_type}." >&2
        return 1
    fi

    printf '%s' "${metadata}"
}

hbs_download_file() {
    local url="${1:-}"
    local output_path="${2:-}"
    local username="${3:-}"
    local password="${4:-}"
    local auth_config="" output_dir tmp_file

    [[ -n "${url}" ]] || {
        echo "ERROR: Download URL is required." >&2
        return 1
    }

    output_dir="$(dirname "${output_path}")"
    mkdir -p "${output_dir}"
    tmp_file="$(mktemp "${output_dir}/.$(basename "${output_path}").part.XXXXXX")"

    hbs_prepare_download_curl_args 1800 || {
        rm -f "${tmp_file}"
        return 1
    }
    if [[ -n "${username}" || -n "${password}" ]]; then
        auth_config="$(hbs_make_curl_auth_config "${username}" "${password}")"
        _hbs_download_curl_args+=(-K "${auth_config}")
    fi
    _hbs_download_curl_args+=(-o "${tmp_file}")

    if ! curl "${_hbs_download_curl_args[@]}" "${url}"; then
        rm -f "${auth_config}"
        rm -f "${tmp_file}"
        echo "ERROR: Failed to download ${url}." >&2
        return 1
    fi
    rm -f "${auth_config}"

    mv -f "${tmp_file}" "${output_path}"
}

hbs_local_sudo_prefix() {
    if [[ -n "${SPLUNK_LOCAL_SUDO:-}" ]]; then
        if hbs_bool_is_true "${SPLUNK_LOCAL_SUDO}"; then
            printf '%s' "sudo"
        fi
        return 0
    fi
    if [[ "$(id -u)" -eq 0 ]]; then
        return 0
    fi
    if command -v sudo >/dev/null 2>&1; then
        printf '%s' "sudo"
    fi
}

hbs_target_sudo_prefix() {
    local execution_mode="${1:-local}"
    if [[ "${execution_mode}" == "local" ]]; then
        hbs_local_sudo_prefix
        return 0
    fi

    if hbs_bool_is_true "${SPLUNK_REMOTE_SUDO:-true}"; then
        printf '%s' "sudo"
    fi
}

hbs_prefix_with_sudo() {
    local execution_mode="${1:-local}"
    local raw_cmd="${2:-}"
    local prefix
    prefix="$(hbs_target_sudo_prefix "${execution_mode}")"
    if [[ -n "${prefix}" ]]; then
        printf '%s %s' "${prefix}" "${raw_cmd}"
    else
        printf '%s' "${raw_cmd}"
    fi
}

hbs_load_ssh_for_execution() {
    local execution_mode="${1:-local}"
    if [[ "${execution_mode}" != "ssh" ]]; then
        return 0
    fi
    load_splunk_ssh_credentials
}

hbs_make_sshpass_file() {
    # NOTE: This function is invoked via $(hbs_make_sshpass_file) in every
    # call site, which forks a subshell. Any EXIT trap registered here would
    # fire on subshell exit and delete the temp file BEFORE the caller can
    # use it — so we deliberately do not register one. Each caller is
    # responsible for `rm -f "${pass_file}"` after the sshpass call.
    local pass_file
    pass_file="$(mktemp)"
    chmod 600 "${pass_file}"
    printf '%s' "${SPLUNK_SSH_PASS}" > "${pass_file}"
    printf '%s' "${pass_file}"
}

hbs_run_target_cmd() {
    local execution_mode="${1:-local}"
    local raw_cmd="${2:-}"
    local quoted pass_file ssh_target

    if [[ "${execution_mode}" == "local" ]]; then
        bash -lc "${raw_cmd}"
        return $?
    fi

    hbs_load_ssh_for_execution "${execution_mode}" || return 1
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "ERROR: sshpass is required for SSH bootstrap mode." >&2
        return 1
    fi

    printf -v quoted '%q' "${raw_cmd}"
    pass_file="$(hbs_make_sshpass_file)"
    ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"

    sshpass -f "${pass_file}" ssh \
        -p "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -q \
        "${ssh_target}" "bash -lc ${quoted}"
    local rc=$?
    rm -f "${pass_file}"
    return "${rc}"
}

hbs_run_target_cmd_with_stdin() {
    local execution_mode="${1:-local}"
    local raw_cmd="${2:-}"
    local stdin_content="${3:-}"
    local quoted pass_file ssh_target

    if [[ -z "${stdin_content}" ]]; then
        hbs_run_target_cmd "${execution_mode}" "${raw_cmd}"
        return $?
    fi

    if [[ "${execution_mode}" == "local" ]]; then
        bash -lc "${raw_cmd}" <<<"${stdin_content}"
        return $?
    fi

    hbs_load_ssh_for_execution "${execution_mode}" || return 1
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "ERROR: sshpass is required for SSH bootstrap mode." >&2
        return 1
    fi

    printf -v quoted '%q' "${raw_cmd}"
    pass_file="$(hbs_make_sshpass_file)"
    ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"

    sshpass -f "${pass_file}" ssh \
        -p "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -q \
        "${ssh_target}" "bash -lc ${quoted}" <<<"${stdin_content}"
    local rc=$?
    rm -f "${pass_file}"
    return "${rc}"
}

hbs_capture_target_cmd() {
    local execution_mode="${1:-local}"
    local raw_cmd="${2:-}"
    local quoted pass_file ssh_target

    if [[ "${execution_mode}" == "local" ]]; then
        bash -lc "${raw_cmd}"
        return $?
    fi

    hbs_load_ssh_for_execution "${execution_mode}" || return 1
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "ERROR: sshpass is required for SSH bootstrap mode." >&2
        return 1
    fi

    printf -v quoted '%q' "${raw_cmd}"
    pass_file="$(hbs_make_sshpass_file)"
    ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"

    sshpass -f "${pass_file}" ssh \
        -p "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -q \
        "${ssh_target}" "bash -lc ${quoted}"
    local rc=$?
    rm -f "${pass_file}"
    return "${rc}"
}

hbs_stage_file_for_execution() {
    local execution_mode="${1:-local}"
    local local_path="${2:-}"
    local remote_name="${3:-}"
    local remote_dir remote_path upload_path upload_dir pass_file ssh_target

    if [[ "${execution_mode}" == "local" ]]; then
        hbs_resolve_abs_path "${local_path}"
        return 0
    fi

    hbs_load_ssh_for_execution "${execution_mode}" || return 1
    if ! command -v sshpass >/dev/null 2>&1; then
        echo "ERROR: sshpass is required for SSH bootstrap mode." >&2
        return 1
    fi

    remote_dir="${SPLUNK_REMOTE_TMPDIR:-/tmp}"
    remote_path="${remote_dir%/}/${remote_name:-$(basename "${local_path}")}"
    upload_dir="/tmp"
    upload_path="${upload_dir%/}/${remote_name:-$(basename "${local_path}")}.stage.$$"

    if [[ "${SPLUNK_SSH_USER}" == "root" ]]; then
        upload_dir="${remote_dir}"
        upload_path="${upload_dir%/}/${remote_name:-$(basename "${local_path}")}.stage.$$"
    fi

    hbs_run_target_cmd "${execution_mode}" "$(hbs_shell_join mkdir -p "${upload_dir}")" >/dev/null
    if [[ "${remote_dir}" != "${upload_dir}" ]]; then
        hbs_run_target_cmd "${execution_mode}" "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join mkdir -p "${remote_dir}")")" >/dev/null
    fi

    pass_file="$(hbs_make_sshpass_file)"
    ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"

    sshpass -f "${pass_file}" scp \
        -P "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -q \
        "${local_path}" "${ssh_target}:${upload_path}"
    local rc=$?
    rm -f "${pass_file}"
    if [[ "${rc}" -ne 0 ]]; then
        echo "ERROR: Failed to stage ${local_path} to ${upload_path}." >&2
        return "${rc}"
    fi

    hbs_run_target_cmd "${execution_mode}" \
        "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join install -m 600 "${upload_path}" "${remote_path}")")" >/dev/null || {
        hbs_remove_target_path "${execution_mode}" "${upload_path}"
        return 1
    }
    hbs_remove_target_path "${execution_mode}" "${upload_path}"

    printf '%s' "${remote_path}"
}

hbs_remove_target_path() {
    local execution_mode="${1:-local}"
    local target_path="${2:-}"
    [[ -n "${target_path}" ]] || return 0
    hbs_run_target_cmd "${execution_mode}" "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join rm -f "${target_path}")")" >/dev/null 2>&1 || true
}

hbs_copy_file_to_target() {
    local execution_mode="${1:-local}"
    local source_path="${2:-}"
    local target_path="${3:-}"
    local file_mode="${4:-600}"
    local backup_existing="${5:-true}"
    local target_dir staged backup_path backup_cmd=""
    target_dir="$(dirname "${target_path}")"
    backup_path="${target_path}.bak.$(date '+%Y%m%d%H%M%S')"

    if [[ "${backup_existing}" == "true" ]]; then
        backup_cmd="if [[ -f $(hbs_shell_join "${target_path}") ]]; then $(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join cp "${target_path}" "${backup_path}")"); fi && "
    fi

    if [[ "${execution_mode}" == "local" ]]; then
        hbs_run_target_cmd "${execution_mode}" \
            "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join mkdir -p "${target_dir}")") && ${backup_cmd}$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join install -m "${file_mode}" "${source_path}" "${target_path}")")"
        return $?
    fi

    staged="$(hbs_stage_file_for_execution "${execution_mode}" "${source_path}" "$(basename "${target_path}").stage.$$")" || return 1
    hbs_run_target_cmd "${execution_mode}" \
        "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join mkdir -p "${target_dir}")") && ${backup_cmd}$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join install -m "${file_mode}" "${staged}" "${target_path}")")"
    local rc=$?
    hbs_remove_target_path "${execution_mode}" "${staged}"
    return "${rc}"
}

hbs_write_target_file() {
    local execution_mode="${1:-local}"
    local target_path="${2:-}"
    local file_mode="${3:-600}"
    local content="${4:-}"
    local backup_existing="${5:-true}"
    local temp_file

    temp_file="$(mktemp)"
    printf '%s' "${content}" > "${temp_file}"
    hbs_copy_file_to_target "${execution_mode}" "${temp_file}" "${target_path}" "${file_mode}" "${backup_existing}"
    local rc=$?
    rm -f "${temp_file}"
    return "${rc}"
}

hbs_detect_advertise_host() {
    local execution_mode="${1:-local}"
    if [[ -n "${SPLUNK_HOST:-}" ]]; then
        printf '%s' "${SPLUNK_HOST}"
        return 0
    fi

    hbs_capture_target_cmd "${execution_mode}" "hostname -f 2>/dev/null || hostname"
}

hbs_run_as_user_cmd() {
    local execution_mode="${1:-local}"
    local target_user="${2:-}"
    local raw_cmd="${3:-}"
    local current_user wrapped_cmd

    if [[ "${execution_mode}" == "local" ]]; then
        current_user="$(id -un)"
        if [[ "${current_user}" == "${target_user}" ]]; then
            hbs_run_target_cmd "${execution_mode}" "${raw_cmd}"
            return $?
        fi
        if command -v sudo >/dev/null 2>&1; then
            wrapped_cmd="$(hbs_shell_join sudo -u "${target_user}" bash -lc "${raw_cmd}")"
        elif [[ "$(id -u)" -eq 0 ]]; then
            wrapped_cmd="$(hbs_shell_join su -s /bin/bash "${target_user}" -c "${raw_cmd}")"
        else
            echo "ERROR: Need sudo or root to run commands as ${target_user} locally." >&2
            return 1
        fi
        hbs_run_target_cmd "${execution_mode}" "${wrapped_cmd}"
        return $?
    fi

    current_user="${SPLUNK_SSH_USER:-}"
    if [[ "${current_user}" == "${target_user}" ]]; then
        hbs_run_target_cmd "${execution_mode}" "${raw_cmd}"
        return $?
    fi
    if [[ "${current_user}" == "root" ]]; then
        wrapped_cmd="$(hbs_shell_join su -s /bin/bash "${target_user}" -c "${raw_cmd}")"
    else
        wrapped_cmd="$(hbs_shell_join sudo -u "${target_user}" bash -lc "${raw_cmd}")"
    fi
    hbs_run_target_cmd "${execution_mode}" "${wrapped_cmd}"
}

hbs_run_as_user_cmd_with_stdin() {
    local execution_mode="${1:-local}"
    local target_user="${2:-}"
    local raw_cmd="${3:-}"
    local stdin_content="${4:-}"
    local current_user wrapped_cmd

    if [[ "${execution_mode}" == "local" ]]; then
        current_user="$(id -un)"
        if [[ "${current_user}" == "${target_user}" ]]; then
            hbs_run_target_cmd_with_stdin "${execution_mode}" "${raw_cmd}" "${stdin_content}"
            return $?
        fi
        if command -v sudo >/dev/null 2>&1; then
            wrapped_cmd="$(hbs_shell_join sudo -u "${target_user}" bash -lc "${raw_cmd}")"
        elif [[ "$(id -u)" -eq 0 ]]; then
            wrapped_cmd="$(hbs_shell_join su -s /bin/bash "${target_user}" -c "${raw_cmd}")"
        else
            echo "ERROR: Need sudo or root to run commands as ${target_user} locally." >&2
            return 1
        fi
        hbs_run_target_cmd_with_stdin "${execution_mode}" "${wrapped_cmd}" "${stdin_content}"
        return $?
    fi

    current_user="${SPLUNK_SSH_USER:-}"
    if [[ "${current_user}" == "${target_user}" ]]; then
        hbs_run_target_cmd_with_stdin "${execution_mode}" "${raw_cmd}" "${stdin_content}"
        return $?
    fi
    if [[ "${current_user}" == "root" ]]; then
        wrapped_cmd="$(hbs_shell_join su -s /bin/bash "${target_user}" -c "${raw_cmd}")"
    else
        wrapped_cmd="$(hbs_shell_join sudo -u "${target_user}" bash -lc "${raw_cmd}")"
    fi
    hbs_run_target_cmd_with_stdin "${execution_mode}" "${wrapped_cmd}" "${stdin_content}"
}

hbs_capture_as_user_cmd() {
    local execution_mode="${1:-local}"
    local target_user="${2:-}"
    local raw_cmd="${3:-}"
    local current_user wrapped_cmd

    if [[ "${execution_mode}" == "local" ]]; then
        current_user="$(id -un)"
        if [[ "${current_user}" == "${target_user}" ]]; then
            hbs_capture_target_cmd "${execution_mode}" "${raw_cmd}"
            return $?
        fi
        if command -v sudo >/dev/null 2>&1; then
            wrapped_cmd="$(hbs_shell_join sudo -u "${target_user}" bash -lc "${raw_cmd}")"
        elif [[ "$(id -u)" -eq 0 ]]; then
            wrapped_cmd="$(hbs_shell_join su -s /bin/bash "${target_user}" -c "${raw_cmd}")"
        else
            echo "ERROR: Need sudo or root to run commands as ${target_user} locally." >&2
            return 1
        fi
        hbs_capture_target_cmd "${execution_mode}" "${wrapped_cmd}"
        return $?
    fi

    current_user="${SPLUNK_SSH_USER:-}"
    if [[ "${current_user}" == "${target_user}" ]]; then
        hbs_capture_target_cmd "${execution_mode}" "${raw_cmd}"
        return $?
    fi
    if [[ "${current_user}" == "root" ]]; then
        wrapped_cmd="$(hbs_shell_join su -s /bin/bash "${target_user}" -c "${raw_cmd}")"
    else
        wrapped_cmd="$(hbs_shell_join sudo -u "${target_user}" bash -lc "${raw_cmd}")"
    fi
    hbs_capture_target_cmd "${execution_mode}" "${wrapped_cmd}"
}
