#!/usr/bin/env bash
# Shared helpers for bootstrapping Splunk Enterprise hosts.
# Source this after credential_helpers.sh.

[[ -n "${_HOST_BOOTSTRAP_HELPERS_LOADED:-}" ]] && return 0
_HOST_BOOTSTRAP_HELPERS_LOADED=true

HBS_ENTERPRISE_DOWNLOAD_PAGE_URL="${HBS_ENTERPRISE_DOWNLOAD_PAGE_URL:-https://www.splunk.com/en_us/download/splunk-enterprise.html}"
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

hbs_detect_package_type() {
    local source_path="${1:-}"
    local lower_name
    lower_name="$(basename "${source_path}" | tr '[:upper:]' '[:lower:]')"
    case "${lower_name}" in
        *.tar.gz|*.tgz) printf '%s' "tgz" ;;
        *.rpm) printf '%s' "rpm" ;;
        *.deb) printf '%s' "deb" ;;
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
match = re.search(r"splunk-(\d+(?:\.\d+)+)-", os.path.basename(source))
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

hbs_prepare_download_curl_args() {
    local max_time="${1:-600}"

    _set_app_download_curl_tls_args || return 1
    _hbs_download_curl_args=(-sSLf --retry 3 --retry-delay 1 --connect-timeout 15 --max-time "${max_time}")
    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_app_download_curl_tls_args.
    if [[ ${#_tls_verify_args[@]} -gt 0 ]]; then
        _hbs_download_curl_args+=("${_tls_verify_args[@]}")
    fi
}

hbs_fetch_url_text() {
    local url="${1:-}"
    local username="${2:-}"
    local password="${3:-}"
    local page_text

    [[ -n "${url}" ]] || {
        echo "ERROR: Download URL is required." >&2
        return 1
    }

    hbs_prepare_download_curl_args 180 || return 1
    if [[ -n "${username}" || -n "${password}" ]]; then
        _hbs_download_curl_args+=(--user "${username}:${password}")
    fi

    page_text="$(curl "${_hbs_download_curl_args[@]}" "${url}" 2>/dev/null)" || {
        echo "ERROR: Failed to fetch ${url}." >&2
        return 1
    }

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

hbs_download_file() {
    local url="${1:-}"
    local output_path="${2:-}"
    local username="${3:-}"
    local password="${4:-}"
    local output_dir tmp_file

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
        _hbs_download_curl_args+=(--user "${username}:${password}")
    fi
    _hbs_download_curl_args+=(-o "${tmp_file}")

    if ! curl "${_hbs_download_curl_args[@]}" "${url}"; then
        rm -f "${tmp_file}"
        echo "ERROR: Failed to download ${url}." >&2
        return 1
    fi

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
