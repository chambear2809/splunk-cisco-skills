#!/usr/bin/env python3
"""Render Splunk HTTP Event Collector service assets."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path


GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "inputs.conf.template",
    "acs-hec-token.json",
    "acs-hec-token-bulk.json",
    "preflight.sh",
    "apply-enterprise-files.sh",
    "apply-cloud-acs.sh",
    "status-enterprise.sh",
    "status-cloud-acs.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk HEC service assets.")
    parser.add_argument("--platform", choices=("enterprise", "cloud"), default="enterprise")
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
        (args.description, "--description"),
        (args.source, "--source"),
        (args.sourcetype, "--sourcetype"),
        (args.token_file, "--token-file"),
        (args.write_token_file, "--write-token-file"),
    ):
        no_newline(value, option)


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
    return f"""# Splunk HEC Service Rendered Assets

Platform: `{args.platform}`
Token name: `{args.token_name}`
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


def render_preflight(args: argparse.Namespace) -> str:
    splunk_home = shell_quote(args.splunk_home)
    helper = shell_quote(helper_path())
    if args.platform == "enterprise":
        return make_script(
            f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool inputs list http --debug >/dev/null
"""
        )
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context
if acs_command hec-token list --count 1 >/dev/null 2>&1; then
  acs_command hec-token list --count 1 >/dev/null
else
  acs_command http-event-collectors list >/dev/null
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
        f"""splunk_home={splunk_home}
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

if [[ -L "${{token_file}}" ]]; then
  echo "ERROR: Refusing symlink HEC token file: ${{token_file}}" >&2
  exit 1
fi
if [[ ! -s "${{token_file}}" ]]; then
  mkdir -p "$(dirname "${{token_file}}")"
  previous_umask="$(umask)"
  umask 077
  python3 - <<'PY' > "${{token_file}}"
import uuid
print(uuid.uuid4(), end="")
PY
  umask "${{previous_umask}}"
fi

if [[ ! -s "${{token_file}}" ]]; then
  echo "ERROR: HEC token file is empty: ${{token_file}}" >&2
  exit 1
fi
chmod 600 "${{token_file}}"

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
import sys
import tempfile

token_path = Path(sys.argv[1])
template_path = Path(sys.argv[2])
target_path = Path(sys.argv[3])
token = token_path.read_text(encoding="utf-8").strip()
if not token:
    raise SystemExit(f"ERROR: token file is empty: {{token_path}}")
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
  if acs_command hec-token list --count 1 >/dev/null 2>&1; then
    printf '%s' "hec-token"
  elif acs_command http-event-collectors list >/dev/null 2>&1; then
    printf '%s' "http-event-collectors"
  else
    log_local "ERROR: Unable to list ACS HEC tokens with either supported command group."
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

cloud_get_hec_token_state() {{
  local token_name="$1" cmd_group hec_list tmp
  cmd_group="$(acs_hec_command_group)"
  if [[ "${{cmd_group}}" == "hec-token" ]]; then
    if ! hec_list=$(acs_command hec-token list --count 100 2>/dev/null | acs_extract_http_response_json); then
      printf '%s' "unknown"
      return 0
    fi
  else
    if ! hec_list=$(acs_command http-event-collectors list 2>/dev/null | acs_extract_http_response_json); then
      printf '%s' "unknown"
      return 0
    fi
  fi
  tmp="$(mktemp)"
  chmod 600 "${{tmp}}"
  printf '%s' "${{hec_list}}" > "${{tmp}}"
  python3 - "${{token_name}}" "${{tmp}}" <<'PY'
import json
import sys
from pathlib import Path

target = sys.argv[1]
payload_path = Path(sys.argv[2])
try:
    data = json.loads(payload_path.read_text(encoding="utf-8"))
    collectors = (
        data.get("http-event-collectors")
        or data.get("http_event_collectors")
        or data.get("tokens")
        or []
    )
    for collector in collectors:
        spec = collector.get("spec", {{}}) if isinstance(collector, dict) else {{}}
        name = spec.get("name") or collector.get("name", "")
        if name != target:
            continue
        disabled = str(spec.get("disabled", collector.get("disabled", False))).strip().lower()
        print("disabled" if disabled in ("1", "true") else "enabled", end="")
        raise SystemExit(0)
    print("missing", end="")
except Exception:
    print("unknown", end="")
PY
  rm -f "${{tmp}}"
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

acs_prepare_context
cmd_group="$(acs_hec_command_group)"
state="$(cloud_get_hec_token_state "${{TOKEN_NAME}}")"
if [[ "${{state}}" == "unknown" ]]; then
  log_local "ERROR: Could not determine whether HEC token '${{TOKEN_NAME}}' already exists. Aborting to avoid duplicate token creation."
  exit 1
fi
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
  output="$(acs_command "${{ACS_ARGS[@]}}" 2>&1)" || {{ printf '%s\\n' "${{output}}" >&2; exit 1; }}
  if ! write_token_from_output "${{output}}"; then
    log_local "ERROR: ACS created HEC token '${{TOKEN_NAME}}', but its one-time token value was not returned or could not be written."
    log_local "HANDOFF: Rotate or recreate the token in the supported Splunk Cloud HEC surface, store it in '${{WRITE_TOKEN_FILE}}', then run status-cloud-acs.sh."
    exit 1
  fi
  log_local "Created HEC token '${{TOKEN_NAME}}' via ACS command group '${{cmd_group}}'."
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
    acs_command "${{ACS_ARGS[@]}}" >/dev/null
  else
    log_local "ERROR: Existing HEC token '${{TOKEN_NAME}}' cannot be reconciled by legacy ACS command group '${{cmd_group}}'."
    log_local "HANDOFF: Apply acs-hec-token.json in the supported Splunk Cloud HEC management surface, then run status-cloud-acs.sh."
    exit 1
  fi
  log_local "HEC token '${{TOKEN_NAME}}' already exists with state '${{state}}'."
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
        f"""splunk_home={splunk_home}
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
TOKEN_NAME={token_name}
acs_prepare_context
tmp="$(mktemp)"
chmod 600 "${{tmp}}"
trap 'rm -f "${{tmp}}"' EXIT
if acs_command hec-token describe "${{TOKEN_NAME}}" >"${{tmp}}" 2>/dev/null; then
  cat "${{tmp}}" | acs_extract_http_response_json
else
  acs_command http-event-collectors describe "${{TOKEN_NAME}}" 2>/dev/null | acs_extract_http_response_json
fi | python3 -c '
import json
import sys

def redact(value):
    if isinstance(value, dict):
        return {{k: ("<redacted>" if k.lower() == "token" else redact(v)) for k, v in value.items()}}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value

try:
    data = json.load(sys.stdin)
except Exception as exc:
    print(f"ERROR: ACS returned invalid JSON: {{exc}}", file=sys.stderr)
    raise SystemExit(1)
if data in ({{}}, []):
    print("ERROR: ACS returned an empty HEC token description.", file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(redact(data), indent=2, sort_keys=True))
'
rm -f "${{tmp}}"
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
    return {
        "target": "hec-service",
        "platform": args.platform,
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
