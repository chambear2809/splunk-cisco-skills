#!/usr/bin/env python3
"""Render Splunk HTTP Event Collector service assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import stat
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
_PLATFORM_VERSION_HELPERS = _SKILLS_ROOT / "shared" / "lib" / "platform_version_helpers.sh"
_SPV_VERSIONS_JSON = _SKILLS_ROOT / "shared" / "references" / "splunk_platform_versions.json"
_SPV_VERSIONS_PY = _SKILLS_ROOT / "shared" / "lib" / "platform_versions.py"
_SPV_BUNDLE_DIR = ".spv-bundle"

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "inputs.conf.template",
    "acs-hec-token.json",
    "acs-hec-token-bulk.json",
    "platform_version_helpers.sh",
    "preflight.sh",
    "apply-enterprise-files.sh",
    "apply-cloud-acs.sh",
    "status-enterprise.sh",
    "status-cloud-acs.sh",
}

EMBEDDED_PRIVATE_SECRET_READER = r'''def read_private_secret(path_value, label):
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise SystemExit(
            f"ERROR: {label} cannot be read safely: O_NOFOLLOW/geteuid is unavailable"
        )
    path = Path(path_value).expanduser()
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SystemExit(
            f"ERROR: {label} must be a readable, non-symlink regular file: {path}: {exc}"
        )
    try:
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit(f"ERROR: {label} must be a single-link regular file: {path}")
        if before.st_uid != os.geteuid():
            raise SystemExit(f"ERROR: {label} must be owned by the current user: {path}")
        if mode & 0o077:
            raise SystemExit(
                f"ERROR: {label} permissions must be 0600 or stricter: {path} has {mode:04o}"
            )
        if not 1 <= before.st_size <= 65536:
            raise SystemExit(
                f"ERROR: {label} size must be between 1 and 65536 bytes: {path}"
            )
        chunks = []
        remaining = 65537
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        data = b"".join(chunks)
        before_fingerprint = (
            before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns, before.st_nlink,
        )
        after_fingerprint = (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
        )
        if before_fingerprint != after_fingerprint or len(data) != before.st_size:
            raise SystemExit(f"ERROR: {label} changed while it was read: {path}")
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SystemExit(f"ERROR: {label} must contain UTF-8 text: {path}: {exc}")
    if len(lines) != 1 or "\x00" in lines[0] or not lines[0].strip():
        raise SystemExit(
            f"ERROR: {label} must contain exactly one non-empty line: {path}"
        )
    return lines[0].strip()
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk HEC service assets.")
    parser.add_argument("--platform", choices=("enterprise", "cloud"), default="enterprise")
    parser.add_argument("--stack", default="")
    parser.add_argument("--search-head", default="")
    parser.add_argument("--acs-server", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="splunk_httpinput")
    parser.add_argument("--token-name", default="cisco_skills_hec")
    parser.add_argument("--description", default="Managed by splunk-hec-service-setup")
    parser.add_argument("--default-index", default="main")
    parser.add_argument("--allowed-indexes", default="main")
    parser.add_argument("--source", default="")
    parser.add_argument("--sourcetype", default="")
    parser.add_argument("--port", default="8088")
    parser.add_argument("--enable-ssl", choices=("true", "false"), default="true")
    parser.add_argument("--global-disabled", choices=("true", "false"), default="false")
    parser.add_argument("--token-disabled", choices=("true", "false"), default="false")
    parser.add_argument("--use-ack", choices=("true", "false"), default="false")
    parser.add_argument(
        "--s2s-indexes-validation",
        choices=("disabled", "disabled_for_internal", "enabled_for_all"),
        default="disabled_for_internal",
    )
    parser.add_argument("--token-file", default="")
    parser.add_argument("--write-token-file", default="")
    parser.add_argument("--restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def bool_value(value: str) -> bool:
    return value.lower() == "true"


def bool_conf(value: str) -> str:
    return "1" if bool_value(value) else "0"


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def conf_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value or ""):
        die(f"{option} must contain only letters, numbers, underscore, dot, colon, or hyphen.")


def index_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[_A-Za-z0-9][A-Za-z0-9_.-]*", value or ""):
        die(f"{option} contains an invalid Splunk index name: {value!r}.")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def cloud_identity(value: str, option: str, *, required: bool = False) -> None:
    if not value and not required:
        return
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value or ""):
        requirement = " is required and" if required else ""
        die(
            f"{option}{requirement} must contain only letters, numbers, "
            "underscore, dot, or hyphen."
        )


def positive_port(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or ""):
        die(f"{option} must be a TCP port number.")
    port = int(value)
    if port < 1 or port > 65535:
        die(f"{option} must be between 1 and 65535.")
    return port


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def validate(args: argparse.Namespace) -> None:
    conf_name(args.app_name, "--app-name")
    conf_name(args.token_name, "--token-name")
    index_name(args.default_index, "--default-index")
    allowed = csv_list(args.allowed_indexes)
    if not allowed:
        die("--allowed-indexes must contain at least one index.")
    for item in allowed:
        index_name(item, "--allowed-indexes")
    if args.default_index not in allowed:
        die("--default-index must also appear in --allowed-indexes.")
    positive_port(args.port, "--port")
    for value, option in (
        (args.stack, "--stack"),
        (args.search_head, "--search-head"),
        (args.acs_server, "--acs-server"),
        (args.description, "--description"),
        (args.source, "--source"),
        (args.sourcetype, "--sourcetype"),
        (args.token_file, "--token-file"),
        (args.write_token_file, "--write-token-file"),
    ):
        no_newline(value, option)
    if args.platform == "cloud":
        cloud_identity(args.stack, "--stack", required=True)
        cloud_identity(args.search_head, "--search-head")
        if args.acs_server not in {
            "https://admin.splunk.com",
            "https://staging.admin.splunk.com",
        }:
            die(
                "--acs-server must be https://admin.splunk.com or "
                "https://staging.admin.splunk.com for Splunk Cloud rendering."
            )
    elif args.stack or args.search_head or args.acs_server:
        die("--stack, --search-head, and --acs-server are valid only with --platform cloud.")


def render_inputs_template(args: argparse.Namespace) -> str:
    lines = [
        "# Rendered by splunk-hec-service-setup. Review before applying.",
        "# Token values are intentionally loaded from a local file by apply-enterprise-files.sh.",
        "[http]",
        f"disabled = {bool_conf(args.global_disabled)}",
        f"enableSSL = {bool_conf(args.enable_ssl)}",
        f"port = {positive_port(args.port, '--port')}",
        "",
        f"[http://{args.token_name}]",
        "token = __HEC_TOKEN_FROM_FILE__",
        f"disabled = {bool_conf(args.token_disabled)}",
        f"description = {args.description}",
        f"index = {args.default_index}",
        f"indexes = {','.join(csv_list(args.allowed_indexes))}",
        f"s2s_indexes_validation = {args.s2s_indexes_validation}",
        f"useACK = {bool_conf(args.use_ack)}",
    ]
    if args.source:
        lines.append(f"source = {args.source}")
    if args.sourcetype:
        lines.append(f"sourcetype = {args.sourcetype}")
    return "\n".join(lines).rstrip() + "\n"


def cloud_payload(args: argparse.Namespace) -> dict:
    payload = {
        "allowedIndexes": csv_list(args.allowed_indexes),
        "defaultIndex": args.default_index,
        "disabled": bool_value(args.token_disabled),
        "name": args.token_name,
        "useACK": bool_value(args.use_ack),
    }
    if args.source:
        payload["defaultSource"] = args.source
    if args.sourcetype:
        payload["defaultSourcetype"] = args.sourcetype
    return payload


def render_readme(args: argparse.Namespace, token_path: str) -> str:
    ack_note = ""
    if args.platform == "cloud" and bool_value(args.use_ack):
        ack_note = (
            "\nCloud ACK note: Splunk Cloud ACS exposes `useACK`, but Splunk Cloud "
            "support for indexer acknowledgement is constrained to supported "
            "ingest paths such as AWS Kinesis Firehose. Validate this before use.\n"
        )
    cloud_target_note = ""
    if args.platform == "cloud":
        cloud_target_note = (
            f"ACS control plane: `{args.acs_server}`\n"
            f"Cloud stack: `{args.stack}`\n"
            f"Cloud search head: `{args.search_head or '(stack default)'}`\n"
        )
    return f"""# Splunk HEC Service Rendered Assets

Platform: `{args.platform}`
{cloud_target_note}Token name: `{args.token_name}`
Default index: `{args.default_index}`

Files:

- `inputs.conf.template`
- `acs-hec-token.json`
- `acs-hec-token-bulk.json`
- `preflight.sh`
- `apply-enterprise-files.sh`
- `apply-cloud-acs.sh`
- `status-enterprise.sh`
- `status-cloud-acs.sh`

Enterprise apply reads or creates the local token file at:

`{token_path}`

The rendered files do not contain a HEC token value. The Enterprise apply script
substitutes the token value from the local file at apply time. The Cloud apply
script lets ACS create the token value and can write the returned token to a
local-only file when `--write-token-file` is supplied.{ack_note}
"""


def default_token_path(args: argparse.Namespace, render_dir: Path) -> str:
    if args.token_file:
        return str(Path(args.token_file).expanduser())
    if args.write_token_file:
        return str(Path(args.write_token_file).expanduser())
    return str(render_dir / f".{args.token_name}.token")


def helper_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "skills/shared/lib/credential_helpers.sh"


def cloud_target_binding(args: argparse.Namespace) -> str:
    return f'''ACS_BOUND_TARGET_CONTEXT=true
ACS_BOUND_REQUIRE_CONFIG_MATCH=true
ACS_BOUND_SERVER={shell_quote(args.acs_server)}
ACS_BOUND_SPLUNK_CLOUD_STACK={shell_quote(args.stack)}
ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD={shell_quote(args.search_head)}
SPLUNK_PLATFORM=cloud
export ACS_BOUND_TARGET_CONTEXT ACS_BOUND_REQUIRE_CONFIG_MATCH ACS_BOUND_SERVER
export ACS_BOUND_SPLUNK_CLOUD_STACK ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD SPLUNK_PLATFORM
'''


def enterprise_version_gate(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    return f'''_script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
export SPV_SKILLS_ROOT="${{_script_dir}}/{_SPV_BUNDLE_DIR}"
platform_version_helpers="${{SPLUNK_PLATFORM_VERSION_HELPERS:-${{_script_dir}}/platform_version_helpers.sh}}"
[[ -r "${{platform_version_helpers}}" ]] || {{ echo "ERROR: platform version helper is missing: ${{platform_version_helpers}}" >&2; exit 1; }}
# shellcheck disable=SC1090
source "${{platform_version_helpers}}"
enterprise_version="$(spv_require_supported_splunk_home {splunk_home})"
echo "PASS: supported Splunk Enterprise runtime ${{enterprise_version}}."
'''


def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    helper = shell_quote(helper_path())
    if args.platform == "enterprise":
        return make_script(
            enterprise_version_gate(args)
            + f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool inputs list http --debug >/dev/null
"""
        )
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
{cloud_target_binding(args)}
if ! acs_prepare_context; then
  echo "ERROR: Unable to prepare the requested ACS context." >&2
  exit 1
fi
# Select a local command surface before the remote check; never use a remote
# auth/transport failure as evidence that a legacy fallback is appropriate.
if command acs hec-token list --help >/dev/null 2>&1; then
  acs_command hec-token list --count 1 --offset 0 >/dev/null
elif command acs http-event-collectors describe --help >/dev/null 2>&1; then
  acs_command http-event-collectors list >/dev/null
else
  echo "ERROR: No supported ACS HEC observation command group is available." >&2
  exit 1
fi
"""
    )


def render_enterprise_apply(args: argparse.Namespace, token_path: str) -> str:
    splunk_home = shell_quote(args.splunk_home)
    app_name = shell_quote(args.app_name)
    token_file = shell_quote(token_path)
    restart_orchestrator = shell_quote(
        Path(__file__).resolve().parents[2]
        / "splunk-platform-restart-orchestrator/scripts/setup.sh"
    )
    restart_block = (
        f'''restart_orchestrator={restart_orchestrator}
if [[ ! -x "${{restart_orchestrator}}" ]]; then
  echo "ERROR: HEC config was written, but the topology-aware restart orchestrator is unavailable." >&2
  echo "HANDOFF: Restart through the target topology's supported path, then run status-enterprise.sh." >&2
  exit 1
fi
export SPLUNK_HOME="${{splunk_home}}"
bash "${{restart_orchestrator}}" --restart --accept-restart --operation "HEC inputs.conf activation"
'''
        if bool_value(args.restart_splunk)
        else 'echo "Splunk restart skipped. Restart is normally required for HEC inputs.conf changes."\n'
    )
    return make_script(
        enterprise_version_gate(args)
        + f"""splunk_home={splunk_home}
app_name={app_name}
token_file={token_file}
target_role="${{SPLUNK_TARGET_ROLE:-standalone}}"

case "${{target_role}}" in
  indexer|indexer-peer|cluster-manager|deployer|shc-deployer|shc-member)
    echo "ERROR: Direct HEC file apply is not safe for topology role '${{target_role}}'." >&2
    echo "HANDOFF: Materialize inputs.conf.template with the secure token file inside the managed bundle workflow, then perform a topology-aware activation." >&2
    exit 1
    ;;
esac

mkdir -p "$(dirname "${{token_file}}")"
python3 - "${{token_file}}" <<'PY'
import os
import sys
import uuid

path = os.path.expanduser(sys.argv[1])
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: cannot create the HEC token safely: O_NOFOLLOW is unavailable")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
try:
    descriptor = os.open(path, flags, 0o600)
except FileExistsError:
    raise SystemExit(0)
except OSError as exc:
    raise SystemExit(f"ERROR: cannot create HEC token file {{path}}: {{exc}}")
try:
    os.write(descriptor, str(uuid.uuid4()).encode("ascii"))
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY

target_dir="${{splunk_home}}/etc/apps/${{app_name}}/local"
target_file="${{target_dir}}/inputs.conf"
mkdir -p "${{target_dir}}"
if [[ -f "${{target_file}}" ]]; then
  backup_file="${{target_file}}.bak.$(date +%Y%m%d%H%M%S).$$"
  cp "${{target_file}}" "${{backup_file}}"
  chmod 600 "${{backup_file}}"
fi

python3 - "${{token_file}}" inputs.conf.template "${{target_file}}" <<'PY'
from pathlib import Path
import os
import re
import stat
import sys
import tempfile

{EMBEDDED_PRIVATE_SECRET_READER}

token_path = Path(sys.argv[1]).expanduser()
template_path = Path(sys.argv[2])
target_path = Path(sys.argv[3])
token = read_private_secret(token_path, "HEC token file")
try:
    import uuid
    uuid.UUID(token)
except Exception:
    raise SystemExit(f"ERROR: HEC token must be a GUID value: {{token_path}}")
template = template_path.read_text(encoding="utf-8")
rendered = template.replace("__HEC_TOKEN_FROM_FILE__", token)

header_re = re.compile(r"^\\s*(\\[[^\\]\\r\\n]+\\])\\s*$")


def split_sections(text):
    preamble = []
    sections = []
    current = None
    for line in text.splitlines():
        match = header_re.match(line)
        if match:
            current = [match.group(1), []]
            sections.append(current)
        elif current is None:
            preamble.append(line)
        else:
            current[1].append(line)
    return preamble, sections


def setting_key(line):
    stripped = line.lstrip()
    if not stripped or stripped.startswith(("#", ";")) or "=" not in stripped:
        return ""
    return stripped.split("=", 1)[0].strip().lower()


def setting_keys(lines):
    keys = set()
    for line in lines:
        key = setting_key(line)
        if key:
            keys.add(key)
    return keys


def remove_keys(existing, keys):
    kept = []
    for line in existing:
        if setting_key(line) in keys:
            continue
        kept.append(line)
    return kept


def merge_body(existing, desired):
    kept = remove_keys(existing, setting_keys(desired))
    while kept and not kept[-1].strip():
        kept.pop()
    return kept + ([""] if kept else []) + desired


preamble, existing_sections = split_sections(
    target_path.read_text(encoding="utf-8") if target_path.exists() else ""
)
_, desired_sections = split_sections(rendered)
desired_by_header = {{header.lower(): body for header, body in desired_sections}}
seen = set()
merged_sections = []
for header, body in existing_sections:
    normalized = header.lower()
    if normalized in desired_by_header:
        if normalized not in seen:
            body = merge_body(body, desired_by_header[normalized])
            seen.add(normalized)
        else:
            body = remove_keys(body, setting_keys(desired_by_header[normalized]))
    merged_sections.append((header, body))
for header, body in desired_sections:
    if header.lower() not in seen:
        merged_sections.append((header, body))

output = list(preamble)
while output and not output[-1].strip():
    output.pop()
for header, body in merged_sections:
    if output:
        output.append("")
    output.append(header)
    output.extend(body)
old_umask = os.umask(0o077)
fd, tmp_name = tempfile.mkstemp(prefix="." + target_path.name + ".", dir=target_path.parent)
os.close(fd)
tmp_path = Path(tmp_name)
try:
    tmp_path.write_text("\\n".join(output).rstrip() + "\\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    os.replace(tmp_path, target_path)
finally:
    os.umask(old_umask)
    if tmp_path.exists():
        tmp_path.unlink()
PY
chmod 600 "${{target_file}}"
{restart_block}"""
    )


def render_cloud_apply(args: argparse.Namespace) -> str:
    helper = shell_quote(helper_path())
    token_name = shell_quote(args.token_name)
    default_index = shell_quote(args.default_index)
    allowed_indexes = shell_quote(",".join(csv_list(args.allowed_indexes)))
    default_source = shell_quote(args.source)
    default_sourcetype = shell_quote(args.sourcetype)
    disabled = "true" if bool_value(args.token_disabled) else "false"
    use_ack = "true" if bool_value(args.use_ack) else "false"
    write_token_file = shell_quote(str(Path(args.write_token_file).expanduser())) if args.write_token_file else "''"
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
{cloud_target_binding(args)}
TOKEN_NAME={token_name}
DEFAULT_INDEX={default_index}
ALLOWED_INDEXES={allowed_indexes}
DEFAULT_SOURCE={default_source}
DEFAULT_SOURCETYPE={default_sourcetype}
DISABLED={disabled}
USE_ACK={use_ack}
WRITE_TOKEN_FILE={write_token_file}
ACS_ARGS=()

log_local() {{
  printf '%s\\n' "$*" >&2
}}

acs_hec_command_group() {{
  # Detect only the local CLI surface; a remote/auth failure must not select a fallback.
  if command acs hec-token list --help >/dev/null 2>&1; then
    printf '%s' "hec-token"
  elif command acs http-event-collectors describe --help >/dev/null 2>&1; then
    printf '%s' "http-event-collectors"
  else
    log_local "ERROR: Unable to locate a supported ACS HEC observation command group."
    return 1
  fi
}}

add_flag_if_supported() {{
  local help_text="$1" flag="$2" value="$3"
  if grep -q -- "${{flag}}" <<< "${{help_text}}"; then
    ACS_ARGS+=("${{flag}}" "${{value}}")
    return 0
  fi
  return 1
}}

add_optional_flag_if_supported() {{
  local help_text="$1" flag="$2" value="$3"
  [[ -n "${{value}}" ]] || return 0
  add_flag_if_supported "${{help_text}}" "${{flag}}" "${{value}}"
}}

add_boolean_flag_if_supported() {{
  local help_text="$1" flag="$2" value="$3"
  if grep -q -- "${{flag}}" <<< "${{help_text}}"; then
    ACS_ARGS+=("${{flag}}=${{value}}")
    return 0
  fi
  return 1
}}

add_ack_flag_if_supported() {{
  local help_text="$1" value="$2"
  if grep -q -- "--use-ack" <<< "${{help_text}}"; then
    ACS_ARGS+=("--use-ack=${{value}}")
    return 0
  fi
  if grep -q -- "--useACK" <<< "${{help_text}}"; then
    ACS_ARGS+=("--useACK=${{value}}")
    return 0
  fi
  return 1
}}

unsupported_flag_handoff() {{
  local field="$1" cmd_group="$2"
  log_local "ERROR: ACS command group '${{cmd_group}}' cannot enforce requested HEC field '${{field}}'."
  log_local "HANDOFF: Upgrade ACS CLI or apply acs-hec-token.json in the supported Splunk Cloud HEC management surface, then run status-cloud-acs.sh."
  exit 1
}}

add_allowed_indexes_if_supported() {{
  local help_text="$1" cmd_group="$2" idx
  if ! grep -q -- "--allowed-indexes" <<< "${{help_text}}"; then
    return 1
  fi
  if [[ "${{cmd_group}}" == "hec-token" ]]; then
    IFS=',' read -r -a allowed_index_array <<< "${{ALLOWED_INDEXES}}"
    for idx in "${{allowed_index_array[@]}}"; do
      [[ -n "${{idx}}" ]] && ACS_ARGS+=("--allowed-indexes" "${{idx}}")
    done
  else
    ACS_ARGS+=("--allowed-indexes" "${{ALLOWED_INDEXES}}")
  fi
  return 0
}}

cloud_describe_hec_token_state() {{
  local token_name="$1" cmd_group="$2" output command_succeeded=false
  if output="$(acs_command "${{cmd_group}}" describe "${{token_name}}" 2>&1)"; then
    command_succeeded=true
  fi
  printf '%s' "${{output}}" | python3 -c '
import json
import re
import sys

requested = sys.argv[1]
command_succeeded = sys.argv[2] == "true"
raw = sys.stdin.read()
if not raw.strip() or len(raw.encode("utf-8")) > 1024 * 1024:
    raise SystemExit(1)
try:
    parsed = json.loads(raw)
except Exception:
    parsed = None

def walk(value, depth=0):
    if depth > 8:
        return
    yield value
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "response" and isinstance(child, str):
                try:
                    child = json.loads(child)
                except Exception:
                    continue
            yield from walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child, depth + 1)

def state_from_disabled(value):
    if isinstance(value, bool):
        return "disabled" if value else "enabled"
    normalized = str(value).strip().lower()
    if normalized in ("1", "true"):
        return "disabled"
    if normalized in ("0", "false"):
        return "enabled"
    raise ValueError("invalid disabled value")

if command_succeeded:
    if parsed is None:
        raise SystemExit(1)
    if isinstance(parsed, list):
        http_items = [
            item for item in parsed
            if isinstance(item, dict) and item.get("type") == "http"
        ]
        if len(http_items) != 1:
            raise SystemExit(1)
        status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
        statuses = [http_items[0][key] for key in status_keys if key in http_items[0]]
        if statuses:
            if any(not str(value).isdigit() for value in statuses):
                raise SystemExit(1)
            normalized_statuses = {{int(value) for value in statuses}}
            if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
                raise SystemExit(1)
    observations = []
    for node in walk(parsed):
        if not isinstance(node, dict):
            continue
        spec = node.get("spec")
        if isinstance(spec, dict) and isinstance(spec.get("name"), str) and spec["name"]:
            if "disabled" in spec:
                disabled_value = spec["disabled"]
            elif "disabled" in node:
                disabled_value = node["disabled"]
            else:
                raise SystemExit(1)
            observations.append((spec["name"], state_from_disabled(disabled_value)))
        direct_name = node.get("name") or node.get("tokenName")
        if isinstance(direct_name, str) and direct_name and "disabled" in node:
            observations.append((direct_name, state_from_disabled(node["disabled"])))
    names = {{name for name, _state in observations}}
    states = {{state for name, state in observations if name == requested}}
    if names != {{requested}} or len(states) != 1:
        raise SystemExit(1)
    print(states.pop(), end="")
    raise SystemExit(0)

status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")

def has_404(value):
    if not isinstance(value, dict):
        return False
    values = [str(value[key]).strip() for key in status_keys if key in value]
    return bool(values) and all(item == "404" for item in values)

def exact_http_404(value):
    if isinstance(value, dict):
        return has_404(value)
    if not isinstance(value, list):
        return False
    http_items = [
        item for item in value
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    return len(http_items) == 1 and has_404(http_items[0])

if parsed is not None and exact_http_404(parsed):
    print("missing", end="")
    raise SystemExit(0)

plain = " ".join(raw.split())
plain = re.sub(r"^error:\s*", "", plain, flags=re.IGNORECASE).rstrip(".")
for marker in (chr(34), chr(39), "[", "]"):
    plain = plain.replace(marker, "")
escaped = re.escape(requested)
patterns = (
    rf"^(?:hec[ -]?token|http event collector|token|resource)\s+{{escaped}}\s+(?:is\s+|was\s+)?not[ -]?found$",
    rf"^no such (?:hec[ -]?token|http event collector|token|resource)\s*:?\s*{{escaped}}$",
    rf"^(?:hec[ -]?token|http event collector|token|resource)\s+{{escaped}}\s+does not exist$",
)
if any(re.fullmatch(pattern, plain, flags=re.IGNORECASE) for pattern in patterns):
    print("missing", end="")
    raise SystemExit(0)
raise SystemExit(1)
' "${{token_name}}" "${{command_succeeded}}" 2>/dev/null
}}

cloud_get_hec_token_state() {{
  local token_name="$1" cmd_group raw tmp rc=0 page_result page_count page_state
  local count=100 offset=0 page_number=0 max_pages=100
  if ! cmd_group="$(acs_hec_command_group)"; then
    return 1
  fi
  if [[ "${{cmd_group}}" == "http-event-collectors" ]]; then
    cloud_describe_hec_token_state "${{token_name}}" "${{cmd_group}}"
    return $?
  fi
  while (( page_number < max_pages )); do
    if ! raw="$(acs_command hec-token list --count "${{count}}" --offset "${{offset}}" 2>/dev/null)"; then
      return 1
    fi
    tmp="$(mktemp)" || return 1
    if ! chmod 600 "${{tmp}}" || ! printf '%s' "${{raw}}" > "${{tmp}}"; then
      rm -f "${{tmp}}"
      return 1
    fi
    if page_result="$(python3 - "${{token_name}}" "${{tmp}}" "${{count}}" <<'PY'
import json
import sys
from pathlib import Path

target = sys.argv[1]
payload_path = Path(sys.argv[2])
page_limit = int(sys.argv[3])
try:
    text = payload_path.read_text(encoding="utf-8")
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("ACS HEC inventory page was empty or oversized")
    structured = json.loads(text)
except Exception:
    raise SystemExit(1)

data = structured
if isinstance(structured, list):
    http_items = [
        item for item in structured
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    if len(http_items) != 1:
        raise SystemExit(1)
    item = http_items[0]
    status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
    statuses = [item[key] for key in status_keys if key in item]
    if statuses:
        if any(not str(value).isdigit() for value in statuses):
            raise SystemExit(1)
        normalized_statuses = {{int(value) for value in statuses}}
        if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
            raise SystemExit(1)
    response = item.get("response")
    if not isinstance(response, str) or not response.strip():
        raise SystemExit(1)
    try:
        data = json.loads(response)
    except Exception:
        raise SystemExit(1)
if not isinstance(data, dict):
    raise SystemExit(1)

keys = ("http-event-collectors", "http_event_collectors", "tokens")
present = [key for key in keys if key in data]
if len(present) != 1 or not isinstance(data[present[0]], list):
    raise SystemExit(1)
collectors = data[present[0]]
if len(collectors) > page_limit:
    raise SystemExit(1)
matches = []
for collector in collectors:
    if not isinstance(collector, dict):
        raise SystemExit(1)
    spec = collector.get("spec", {{}})
    if not isinstance(spec, dict):
        raise SystemExit(1)
    name = spec.get("name") or collector.get("name", "")
    if not isinstance(name, str) or not name:
        raise SystemExit(1)
    if name != target:
        continue
    if "disabled" in spec:
        disabled_value = spec["disabled"]
    elif "disabled" in collector:
        disabled_value = collector["disabled"]
    else:
        raise SystemExit(1)
    disabled = str(disabled_value).strip().lower()
    if disabled in ("1", "true"):
        matches.append("disabled")
    elif disabled in ("0", "false"):
        matches.append("enabled")
    else:
        raise SystemExit(1)
if len(matches) > 1:
    raise SystemExit(1)
state = matches[0] if matches else "absent"
print(f"{{len(collectors)}}:{{state}}", end="")
PY
    )"; then
      rc=0
    else
      rc=$?
    fi
    rm -f "${{tmp}}"
    (( rc == 0 )) || return "${{rc}}"
    page_count="${{page_result%%:*}}"
    page_state="${{page_result#*:}}"
    [[ "${{page_count}}" =~ ^[0-9]+$ ]] || return 1
    case "${{page_state}}" in
      enabled|disabled)
        printf '%s' "${{page_state}}"
        return 0
        ;;
      absent) ;;
      *) return 1 ;;
    esac
    if (( page_count < count )); then
      printf 'missing'
      return 0
    fi
    offset=$((offset + count))
    page_number=$((page_number + 1))
  done
  return 1
}}

write_token_from_output() {{
  local output="$1" tmp
  [[ -n "${{WRITE_TOKEN_FILE}}" ]] || return 0
  tmp="$(mktemp)"
  chmod 600 "${{tmp}}"
  printf '%s' "${{output}}" > "${{tmp}}"
  if ! python3 - "${{tmp}}" "${{WRITE_TOKEN_FILE}}" <<'PY'
from pathlib import Path
import json
import os
import sys
import tempfile

raw_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
if target_path.is_symlink():
    raise SystemExit(f"ERROR: refusing symlink token output path: {{target_path}}")
text = raw_path.read_text(encoding="utf-8")

def structured_payload(value):
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict) or item.get("type") != "http":
                continue
            response = item.get("response")
            if isinstance(response, str):
                try:
                    return json.loads(response)
                except Exception:
                    return item
            return item
    return value

def find_token(value):
    if isinstance(value, dict):
        token = value.get("token")
        if isinstance(token, str) and token:
            return token
        for child in value.values():
            found = find_token(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_token(child)
            if found:
                return found
    return ""

try:
    data = structured_payload(json.loads(text))
except Exception:
    data = {{}}

token = find_token(data)
if not token:
    raise SystemExit("ERROR: ACS response did not contain a token value")
target_path.parent.mkdir(parents=True, exist_ok=True)
old_umask = os.umask(0o077)
fd, tmp_name = tempfile.mkstemp(prefix="." + target_path.name + ".", dir=target_path.parent)
os.close(fd)
temp_path = Path(tmp_name)
try:
    temp_path.write_text(token, encoding="utf-8")
    temp_path.chmod(0o600)
    os.replace(temp_path, target_path)
finally:
    os.umask(old_umask)
    if temp_path.exists():
        temp_path.unlink()
PY
  then
    rm -f "${{tmp}}"
    log_local "ERROR: Unable to parse or persist the ACS HEC token response."
    return 1
  fi
  rm -f "${{tmp}}"
}}

if ! acs_prepare_context; then
  log_local "ERROR: Unable to prepare the requested ACS context."
  exit 1
fi
if ! cmd_group="$(acs_hec_command_group)"; then
  exit 1
fi
if ! state="$(cloud_get_hec_token_state "${{TOKEN_NAME}}")"; then
  log_local "ERROR: Could not obtain a trustworthy HEC token inventory through ACS; refusing mutation."
  exit 1
fi
case "${{state}}" in
  enabled|disabled|missing) ;;
  *)
    log_local "ERROR: ACS returned an invalid HEC token state; refusing mutation."
    exit 1
    ;;
esac
if [[ "${{state}}" != "missing" && -n "${{WRITE_TOKEN_FILE}}" ]]; then
  if [[ ! -f "${{WRITE_TOKEN_FILE}}" || -L "${{WRITE_TOKEN_FILE}}" ]] \
      || ! LC_ALL=C grep -q '[^[:space:]]' "${{WRITE_TOKEN_FILE}}"; then
    log_local "ERROR: ACS does not return an existing HEC token secret, and no usable local token file exists at '${{WRITE_TOKEN_FILE}}'."
    log_local "HANDOFF: Rotate/recreate '${{TOKEN_NAME}}', capture its one-time value in that owner-only file, then rerun apply and status."
    exit 1
  fi
  token_mode="$(stat -c '%a' "${{WRITE_TOKEN_FILE}}" 2>/dev/null || stat -f '%Lp' "${{WRITE_TOKEN_FILE}}" 2>/dev/null || true)"
  if [[ ! "${{token_mode}}" =~ ^[0-7]*00$ ]]; then
    log_local "ERROR: Existing token file must not have group/other permission bits: ${{WRITE_TOKEN_FILE}}"
    exit 1
  fi
  log_local "Using the existing owner-only local token file; ACS cannot verify or return the stored secret for an existing token."
fi
if [[ "${{state}}" == "missing" ]]; then
  if [[ "${{cmd_group}}" == "hec-token" ]]; then
    help_text="$(acs_command hec-token create --help 2>&1 || true)"
    ACS_ARGS=(hec-token create --name "${{TOKEN_NAME}}")
  else
    help_text="$(acs_command http-event-collectors create --help 2>&1 || true)"
    ACS_ARGS=(http-event-collectors create --name "${{TOKEN_NAME}}")
  fi
  add_flag_if_supported "${{help_text}}" "--default-index" "${{DEFAULT_INDEX}}" || unsupported_flag_handoff "defaultIndex" "${{cmd_group}}"
  add_allowed_indexes_if_supported "${{help_text}}" "${{cmd_group}}" || unsupported_flag_handoff "allowedIndexes" "${{cmd_group}}"
  add_optional_flag_if_supported "${{help_text}}" "--default-source" "${{DEFAULT_SOURCE}}" || unsupported_flag_handoff "defaultSource" "${{cmd_group}}"
  add_optional_flag_if_supported "${{help_text}}" "--default-sourcetype" "${{DEFAULT_SOURCETYPE}}" || unsupported_flag_handoff "defaultSourcetype" "${{cmd_group}}"
  add_boolean_flag_if_supported "${{help_text}}" "--disabled" "${{DISABLED}}" || unsupported_flag_handoff "disabled" "${{cmd_group}}"
  add_ack_flag_if_supported "${{help_text}}" "${{USE_ACK}}" || unsupported_flag_handoff "useACK" "${{cmd_group}}"
  if ! output="$(acs_command "${{ACS_ARGS[@]}}" 2>&1)"; then
    log_local "ERROR: ACS failed to create HEC token '${{TOKEN_NAME}}'; refusing to print a potentially sensitive response."
    exit 1
  fi
  if ! write_token_from_output "${{output}}"; then
    log_local "ERROR: The ACS create command returned success for HEC token '${{TOKEN_NAME}}', but its one-time token value was not returned or could not be written; creation is not verified."
    log_local "HANDOFF: Rotate or recreate the token in the supported Splunk Cloud HEC surface, store it in '${{WRITE_TOKEN_FILE}}', then run status-cloud-acs.sh."
    exit 1
  fi
  if ! observed_state="$(cloud_get_hec_token_state "${{TOKEN_NAME}}")"; then
    log_local "ERROR: ACS create returned success, but HEC token '${{TOKEN_NAME}}' could not be read back."
    exit 1
  fi
  expected_state="enabled"
  [[ "${{DISABLED}}" == "true" ]] && expected_state="disabled"
  if [[ "${{observed_state}}" != "${{expected_state}}" ]]; then
    log_local "ERROR: ACS create returned success, but HEC token '${{TOKEN_NAME}}' read back as '${{observed_state}}' instead of '${{expected_state}}'."
    exit 1
  fi
  log_local "Created and read back HEC token '${{TOKEN_NAME}}' via ACS command group '${{cmd_group}}'."
else
  if [[ "${{cmd_group}}" == "hec-token" ]]; then
    help_text="$(acs_command hec-token update --help 2>&1 || true)"
    ACS_ARGS=(hec-token update "${{TOKEN_NAME}}")
    add_flag_if_supported "${{help_text}}" "--default-index" "${{DEFAULT_INDEX}}" || unsupported_flag_handoff "defaultIndex" "${{cmd_group}}"
    add_allowed_indexes_if_supported "${{help_text}}" "${{cmd_group}}" || unsupported_flag_handoff "allowedIndexes" "${{cmd_group}}"
    add_optional_flag_if_supported "${{help_text}}" "--default-source" "${{DEFAULT_SOURCE}}" || unsupported_flag_handoff "defaultSource" "${{cmd_group}}"
    add_optional_flag_if_supported "${{help_text}}" "--default-sourcetype" "${{DEFAULT_SOURCETYPE}}" || unsupported_flag_handoff "defaultSourcetype" "${{cmd_group}}"
    add_boolean_flag_if_supported "${{help_text}}" "--disabled" "${{DISABLED}}" || unsupported_flag_handoff "disabled" "${{cmd_group}}"
    add_ack_flag_if_supported "${{help_text}}" "${{USE_ACK}}" || unsupported_flag_handoff "useACK" "${{cmd_group}}"
    if ! acs_command "${{ACS_ARGS[@]}}" >/dev/null; then
      log_local "ERROR: ACS failed to update HEC token '${{TOKEN_NAME}}'."
      exit 1
    fi
    if ! observed_state="$(cloud_get_hec_token_state "${{TOKEN_NAME}}")"; then
      log_local "ERROR: ACS update returned success, but HEC token '${{TOKEN_NAME}}' could not be read back."
      exit 1
    fi
    expected_state="enabled"
    [[ "${{DISABLED}}" == "true" ]] && expected_state="disabled"
    if [[ "${{observed_state}}" != "${{expected_state}}" ]]; then
      log_local "ERROR: ACS update returned success, but HEC token '${{TOKEN_NAME}}' read back as '${{observed_state}}' instead of '${{expected_state}}'."
      exit 1
    fi
  else
    log_local "ERROR: Existing HEC token '${{TOKEN_NAME}}' cannot be reconciled by legacy ACS command group '${{cmd_group}}'."
    log_local "HANDOFF: Apply acs-hec-token.json in the supported Splunk Cloud HEC management surface, then run status-cloud-acs.sh."
    exit 1
  fi
  log_local "Updated and read back HEC token '${{TOKEN_NAME}}' with state '${{observed_state}}'."
fi

if [[ "${{USE_ACK}}" == "true" ]]; then
  log_local "Review Splunk Cloud indexer acknowledgement support for this ingest path before production use."
fi
"""
    )


def render_status_enterprise(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    token_name = shell_quote(f"http://{args.token_name}")
    return make_script(
        enterprise_version_gate(args)
        + f"""splunk_home={splunk_home}
output="$("${{splunk_home}}/bin/splunk" btool inputs list {token_name} --debug 2>/dev/null)" || {{
  echo "ERROR: Unable to query HEC stanza {args.token_name}." >&2
  exit 1
}}
if [[ -z "${{output}}" ]]; then
  echo "ERROR: HEC stanza {args.token_name} was not found." >&2
  exit 1
fi
printf '%s\\n' "${{output}}" | awk 'tolower($0) !~ /(^|[[:space:]])token[[:space:]]*=/'
"""
    )


def render_status_cloud(args: argparse.Namespace) -> str:
    helper = shell_quote(helper_path())
    token_name = shell_quote(args.token_name)
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
{cloud_target_binding(args)}
TOKEN_NAME={token_name}
if ! acs_prepare_context; then
  echo "ERROR: Unable to prepare the requested ACS context." >&2
  exit 1
fi
raw_tmp="$(mktemp)"
payload_tmp="$(mktemp)"
chmod 600 "${{raw_tmp}}" "${{payload_tmp}}"
trap 'rm -f "${{raw_tmp}}" "${{payload_tmp}}"' EXIT
if command acs hec-token describe --help >/dev/null 2>&1; then
  if ! acs_command hec-token describe "${{TOKEN_NAME}}" >"${{raw_tmp}}" 2>/dev/null; then
    echo "ERROR: Unable to describe HEC token '${{TOKEN_NAME}}' through ACS." >&2
    exit 1
  fi
elif command acs http-event-collectors describe --help >/dev/null 2>&1; then
  if ! acs_command http-event-collectors describe "${{TOKEN_NAME}}" >"${{raw_tmp}}" 2>/dev/null; then
    echo "ERROR: Unable to describe HEC token '${{TOKEN_NAME}}' through ACS." >&2
    exit 1
  fi
else
  echo "ERROR: No supported ACS HEC describe command group is available." >&2
  exit 1
fi
if ! python3 - "${{raw_tmp}}" "${{payload_tmp}}" <<'PY'
import json
import sys
from pathlib import Path

raw_path = Path(sys.argv[1])
payload_path = Path(sys.argv[2])
try:
    text = raw_path.read_text(encoding="utf-8")
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized ACS response")
    structured = json.loads(text)
except Exception:
    raise SystemExit(1)

payload = structured
if isinstance(structured, list):
    http_items = [
        item for item in structured
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    if len(http_items) != 1:
        raise SystemExit(1)
    item = http_items[0]
    status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
    statuses = [item[key] for key in status_keys if key in item]
    if statuses:
        if any(not str(value).isdigit() for value in statuses):
            raise SystemExit(1)
        normalized_statuses = {{int(value) for value in statuses}}
        if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
            raise SystemExit(1)
    response = item.get("response")
    if not isinstance(response, str) or not response.strip():
        raise SystemExit(1)
    try:
        payload = json.loads(response)
    except Exception:
        raise SystemExit(1)
if not isinstance(payload, dict):
    raise SystemExit(1)
payload_path.write_text(json.dumps(payload), encoding="utf-8")
PY
then
  echo "ERROR: ACS returned an unreadable HEC token description." >&2
  exit 1
fi
python3 - "${{TOKEN_NAME}}" "${{payload_tmp}}" <<'PY'
import json
import sys
from pathlib import Path

target = sys.argv[1]
payload_path = Path(sys.argv[2])
sensitive_fragments = (
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "cookie",
)

def redact(value):
    if isinstance(value, dict):
        return {{
            k: (
                "<redacted>"
                if any(fragment in str(k).lower() for fragment in sensitive_fragments)
                else redact(v)
            )
            for k, v in value.items()
        }}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value

def collect_hec_names(value):
    names = []
    if isinstance(value, dict):
        hec_fields = {{
            "disabled",
            "defaultIndex",
            "defaultindex",
            "default_index",
            "allowedIndexes",
            "useACK",
            "useAck",
            "token",
            "tokenValue",
        }}
        spec = value.get("spec")
        if isinstance(spec, dict):
            spec_name = spec.get("name")
            if isinstance(spec_name, str) and spec_name:
                names.append(spec_name)
        direct_name = value.get("name") or value.get("tokenName")
        if (
            isinstance(direct_name, str)
            and direct_name
            and bool(hec_fields.intersection(value))
        ):
            names.append(direct_name)
        for child in value.values():
            names.extend(collect_hec_names(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(collect_hec_names(child))
    return names

try:
    text = payload_path.read_text(encoding="utf-8")
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized description")
    data = json.loads(text)
except Exception:
    print("ERROR: ACS returned an invalid HEC token description.", file=sys.stderr)
    raise SystemExit(1)
if data in ({{}}, []):
    print("ERROR: ACS returned an empty HEC token description.", file=sys.stderr)
    raise SystemExit(1)
observed_names = set(collect_hec_names(data))
if observed_names != {{target}}:
    print("ERROR: ACS HEC token description did not identify the requested token.", file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(redact(data), indent=2, sort_keys=True))
PY
rm -f "${{raw_tmp}}" "${{payload_tmp}}"
trap - EXIT
"""
    )


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "hec-service"
    token_path = default_token_path(args, render_dir)
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args, token_path),
            "metadata.json": json.dumps(
                {
                    "platform": args.platform,
                    "cloud_stack": args.stack if args.platform == "cloud" else "",
                    "cloud_search_head": args.search_head if args.platform == "cloud" else "",
                    "acs_server": args.acs_server if args.platform == "cloud" else "",
                    "app_name": args.app_name,
                    "token_name": args.token_name,
                    "default_index": args.default_index,
                    "allowed_indexes": csv_list(args.allowed_indexes),
                    "source": args.source,
                    "sourcetype": args.sourcetype,
                    "use_ack": bool_value(args.use_ack),
                    "token_file": token_path,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "inputs.conf.template": render_inputs_template(args),
            "acs-hec-token.json": json.dumps(cloud_payload(args), indent=2, sort_keys=True) + "\n",
            "acs-hec-token-bulk.json": json.dumps({"hec-tokens": [cloud_payload(args)]}, indent=2, sort_keys=True) + "\n",
            "preflight.sh": render_preflight(args),
            "apply-enterprise-files.sh": render_enterprise_apply(args, token_path),
            "apply-cloud-acs.sh": render_cloud_apply(args),
            "status-enterprise.sh": render_status_enterprise(args),
            "status-cloud-acs.sh": render_status_cloud(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
        spv_refs = render_dir / _SPV_BUNDLE_DIR / "shared" / "references"
        spv_lib = render_dir / _SPV_BUNDLE_DIR / "shared" / "lib"
        spv_refs.mkdir(parents=True, exist_ok=True)
        spv_lib.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_SPV_VERSIONS_JSON, spv_refs / "splunk_platform_versions.json")
        shutil.copy2(_SPV_VERSIONS_PY, spv_lib / "platform_versions.py")
        shutil.copy2(_PLATFORM_VERSION_HELPERS, render_dir / "platform_version_helpers.sh")
        assets.append("platform_version_helpers.sh")
        assets.append(f"{_SPV_BUNDLE_DIR}/shared/references/splunk_platform_versions.json")
        assets.append(f"{_SPV_BUNDLE_DIR}/shared/lib/platform_versions.py")
    return {
        "target": "hec-service",
        "platform": args.platform,
        "cloud_stack": args.stack if args.platform == "cloud" else "",
        "cloud_search_head": args.search_head if args.platform == "cloud" else "",
        "acs_server": args.acs_server if args.platform == "cloud" else "",
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": [["./apply-enterprise-files.sh" if args.platform == "enterprise" else "./apply-cloud-acs.sh"]],
            "status": [["./status-enterprise.sh" if args.platform == "enterprise" else "./status-cloud-acs.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render HEC service assets under {payload['render_dir']}")
    else:
        print(f"Rendered HEC service assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
