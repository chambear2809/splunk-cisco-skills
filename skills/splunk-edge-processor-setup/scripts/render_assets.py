#!/usr/bin/env python3
"""Render Splunk Edge Processor assets for both Cloud and Enterprise control planes."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path


VALID_CONTROL_PLANES = ("cloud", "enterprise")
VALID_TLS_MODES = ("none", "tls", "mtls")
VALID_INSTANCE_MODES = ("systemd", "nosystemd", "docker")
VALID_DEST_TYPES = ("s2s", "hec", "s3", "syslog")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render Splunk Edge Processor assets.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--ep-control-plane", choices=VALID_CONTROL_PLANES, default="cloud")
    p.add_argument("--ep-tenant-url", required=True)
    p.add_argument("--ep-name", default="prod-ep")
    p.add_argument("--ep-tls-mode", choices=VALID_TLS_MODES, default="none")
    p.add_argument("--ep-tls-server-cert", default="")
    p.add_argument("--ep-tls-server-key", default="")
    p.add_argument("--ep-tls-ca-cert", default="")
    p.add_argument("--ep-instances", default="")
    p.add_argument("--ep-target-daily-gb", default="50")
    p.add_argument("--ep-source-types", default="")
    p.add_argument("--ep-destinations", default="")
    p.add_argument("--ep-default-destination", default="")
    p.add_argument("--ep-pipelines", default="")
    p.add_argument("--ep-install-dir", default="/opt/splunk-edge")
    p.add_argument("--ep-service-user", default="splunkedge")
    p.add_argument("--ep-service-cgroup", default="splunkedge")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# Instance hostnames are interpolated into rendered file PATHS like
# `host/{host}/install-with-systemd.sh`. We restrict the value to a DNS-
# label / IP character class so a bogus value like `../../etc/passwd`
# cannot escape the operator's chosen output directory.
_HOST_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_host_token(host: str) -> str:
    if not host or not _HOST_RE.fullmatch(host):
        die(
            f"--ep-instances host {host!r} is not a valid hostname/IP token "
            "(allowed: letters, digits, '.', '_', '-')."
        )
    return host


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


# Runtime locator for skills/shared/lib so the rendered scripts can source
# edge_processor_helpers.sh (which feeds the EP Bearer token to curl via
# `-K <(...)` and never via argv `-H`). Mirrors the pattern used by the
# license and indexer-cluster renderers.
_EP_LIB_DIR_BLOCK = (
    '_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    'LIB_DIR="${SKILLS_SHARED_LIB_DIR:-}"\n'
    'if [[ -z "${LIB_DIR}" ]]; then\n'
    '  for candidate in \\\n'
    '    "${_SCRIPT_DIR}/../../../../skills/shared/lib" \\\n'
    '    "${_SCRIPT_DIR}/../../../skills/shared/lib" \\\n'
    '    "${_SCRIPT_DIR}/../../skills/shared/lib"; do\n'
    '    if [[ -d "${candidate}" ]]; then\n'
    '      LIB_DIR="$(cd "${candidate}" && pwd)"\n'
    '      break\n'
    '    fi\n'
    '  done\n'
    'fi\n'
    'if [[ -z "${LIB_DIR}" || ! -d "${LIB_DIR}" ]]; then\n'
    '  echo "ERROR: Could not locate skills/shared/lib. Set SKILLS_SHARED_LIB_DIR=/path/to/skills/shared/lib." >&2\n'
    '  exit 1\n'
    'fi\n'
)


def parse_instances(value: str) -> list[dict]:
    items = []
    for entry in csv_list(value):
        if "=" not in entry:
            die(f"--ep-instances entry needs host=mode: {entry!r}")
        host, mode = entry.split("=", 1)
        host = validate_host_token(host.strip())
        mode = mode.strip()
        if mode not in VALID_INSTANCE_MODES:
            die(f"--ep-instances mode must be {VALID_INSTANCE_MODES}: {entry!r}")
        items.append({"host": host, "mode": mode})
    return items


def parse_destinations(value: str) -> list[dict]:
    """Parse `name=key=value;key=value,name2=key=value;...` strings."""
    if not value.strip():
        return []
    out = []
    for entry in csv_list(value):
        if "=" not in entry:
            die(f"--ep-destinations entry needs name=key=value;...: {entry!r}")
        name, kv_string = entry.split("=", 1)
        name = name.strip()
        spec = {"name": name}
        for kv in kv_string.split(";"):
            kv = kv.strip()
            if not kv:
                continue
            if "=" not in kv:
                die(f"--ep-destinations key=value malformed: {kv!r}")
            k, v = kv.split("=", 1)
            spec[k.strip()] = v.strip()
        if "type" not in spec or spec["type"] not in VALID_DEST_TYPES:
            die(f"--ep-destinations entry must include type in {VALID_DEST_TYPES}: {entry!r}")
        out.append(spec)
    return out


def parse_pipelines(value: str) -> list[dict]:
    if not value.strip():
        return []
    out = []
    for entry in csv_list(value):
        if "=" not in entry:
            die(f"--ep-pipelines entry needs name=key=value;...: {entry!r}")
        name, kv_string = entry.split("=", 1)
        name = name.strip()
        spec = {"name": name}
        for kv in kv_string.split(";"):
            kv = kv.strip()
            if not kv:
                continue
            if "=" not in kv:
                die(f"--ep-pipelines key=value malformed: {kv!r}")
            k, v = kv.split("=", 1)
            spec[k.strip()] = v.strip()
        for required in ("partition", "destination", "spl2_file"):
            if required not in spec:
                die(f"--ep-pipelines missing required key {required!r}: {entry!r}")
        out.append(spec)
    return out


def render_ep_object(args: argparse.Namespace) -> str:
    payload = {
        "name": args.ep_name,
        "tls": {
            "mode": args.ep_tls_mode,
            "server_certificate_path": args.ep_tls_server_cert or None,
            "server_key_path": args.ep_tls_server_key or None,
            "ca_certificate_path": args.ep_tls_ca_cert or None,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_source_type(name: str) -> str:
    return json.dumps(
        {
            "name": name,
            "event_breaking": {"line_breaker": r"([\r\n]+)"},
            "datetime_extraction": {"format": "auto"},
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_destination(spec: dict) -> str:
    payload = {"name": spec["name"], "type": spec["type"]}
    for k, v in spec.items():
        if k in ("name", "type"):
            continue
        payload[k] = v
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_pipeline_payload(spec: dict) -> str:
    payload = {
        "name": spec["name"],
        "partition": {
            "field": next((k for k in spec.keys() if k not in ("name", "partition", "destination", "spl2_file")), ""),
            "operator": "matches",
            "value": "",
            "mode": spec["partition"],
        },
        "destination": spec["destination"],
        "spl2_file": spec["spl2_file"],
    }
    field = payload["partition"]["field"]
    if field:
        raw = spec[field]
        if ":" in raw:
            op, val = raw.split(":", 1)
            payload["partition"]["operator"] = op
            payload["partition"]["value"] = val
        else:
            payload["partition"]["operator"] = "equals"
            payload["partition"]["value"] = raw
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _spl2_string_literal(value: str) -> str:
    """Encode an arbitrary Python string as a safe SPL2 double-quoted literal.

    SPL2 string literals follow the same backslash escape conventions as
    JSON. ``json.dumps`` produces a properly-escaped double-quoted string
    for any input, so values containing ``"``, ``\\``, newlines, tabs, or
    other control characters cannot break out of the literal and inject
    additional pipeline syntax.
    """
    return json.dumps(value, ensure_ascii=False)


def render_pipeline_spl2(spec: dict, destination: dict | None) -> str:
    field = next((k for k in spec.keys() if k not in ("name", "partition", "destination", "spl2_file")), "")
    if field:
        raw = spec[field]
        if ":" in raw:
            op, val = raw.split(":", 1)
        else:
            op, val = "equals", raw
        # Field names are operator-supplied; we keep the existing identifier
        # contract (must match the SPL2 identifier shape). The VALUE is
        # passed through json.dumps so quotes/backslashes/newlines cannot
        # close the string literal and inject SPL2.
        val_lit = _spl2_string_literal(val)
        if op in ("equals",):
            cond = f'{field} == {val_lit}'
        elif op in ("matches",):
            cond = f'match({field}, {val_lit})'
        else:
            cond = f'{field} == {val_lit}'
        if spec["partition"].lower() == "remove":
            cond = f'NOT ({cond})'
    else:
        cond = "true"

    return f"""// Rendered by splunk-edge-processor-setup. Edit and re-render to update.
// Pipeline: {spec['name']}
// Destination: {spec['destination']}

$pipeline = | from $source where {cond}
            | into $destination;
"""


def render_pipeline_templates() -> dict[str, str]:
    return {
        "filter.spl2": (
            "// Filter starter: keep events that match a where clause.\n"
            '$pipeline = | from $source where sourcetype != "noisy:type" | into $destination;\n'
        ),
        "mask.spl2": (
            "// Mask starter: redact a sensitive field with replace().\n"
            "$pipeline = | from $source\n"
            '            | eval _raw = replace(_raw, "(?i)password=\\\\S+", "password=REDACTED")\n'
            "            | into $destination;\n"
        ),
        "sample.spl2": (
            "// Sampling starter: keep ~10% of events using random_int.\n"
            "$pipeline = | from $source where random_int < 10 | into $destination;\n"
        ),
        "route.spl2": (
            "// Routing starter: fan-out to two destinations from one pipeline.\n"
            "$pipeline = | from $source\n"
            "            | branch\n"
            "                [ where sourcetype LIKE \"sec:%\"  | into $destination_security ]\n"
            "                [ where true                       | into $destination_default ];\n"
        ),
    }


def render_instance_install(args: argparse.Namespace, instance: dict) -> str:
    install_dir = shell_quote(args.ep_install_dir)
    user = shell_quote(args.ep_service_user)
    cgroup = shell_quote(args.ep_service_cgroup)
    tenant = shell_quote(args.ep_tenant_url)

    # The Edge Processor install command is generated by the control plane
    # (Manage instances → Install/uninstall → Step 1) and contains a
    # short-lived join token. We do NOT invent an `/api/v1/edge-processor/install`
    # endpoint. Instead the rendered script reads that script body from a
    # local file the operator stages via `write_secret_file.sh`, then runs it
    # under the service user with the token never appearing in argv.
    common_install_cmd_block = (
        "# The EP install command is generated by the control plane (Manage instances UI):\n"
        "#   1. In Splunk Cloud Platform, open Edge Processor -> Manage instances -> Install/uninstall.\n"
        "#   2. Copy the multi-line install command (it contains a short-lived join token).\n"
        "#   3. Stage it locally with `bash skills/shared/scripts/write_secret_file.sh ${INSTALL_CMD_FILE}`.\n"
        "#   4. Re-run this script with EP_INSTALL_CMD_FILE pointing at that file.\n"
        'INSTALL_CMD_FILE="${EP_INSTALL_CMD_FILE:?set EP_INSTALL_CMD_FILE=/path/to/install_cmd.sh (the script you copied from the EP control plane)}"\n'
        'if [[ ! -s "${INSTALL_CMD_FILE}" ]]; then\n'
        '  echo "ERROR: EP install command file missing or empty: ${INSTALL_CMD_FILE}" >&2\n'
        '  exit 1\n'
        'fi\n'
    )

    if instance["mode"] == "systemd":
        body = (
            f"INSTALL_DIR={install_dir}\n"
            f"SERVICE_USER={user}\n"
            f"SERVICE_GROUP={cgroup}\n"
            f"# Tenant URL is for operator reference; the install command itself encodes it.\n"
            f"# shellcheck disable=SC2034\n"
            f"TENANT_URL={tenant}\n\n"
            f"{common_install_cmd_block}\n"
            "# 1. Create cgroup + service user.\n"
            'sudo groupadd -f "${SERVICE_GROUP}"\n'
            'if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then\n'
            '  sudo useradd -d "${INSTALL_DIR}" -g "${SERVICE_GROUP}" -m -s /bin/bash "${SERVICE_USER}"\n'
            'fi\n'
            'sudo mkdir -p "${INSTALL_DIR}"\n'
            'sudo chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}"\n\n'
            "# 2. Stage the operator-supplied install command into the service user's\n"
            "#    home and execute it as that user. Token never appears in argv.\n"
            'sudo install -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" \\\n'
            '  "${INSTALL_CMD_FILE}" "${INSTALL_DIR}/install_cmd.sh"\n'
            'sudo -u "${SERVICE_USER}" -H bash -lc "cd \\"${INSTALL_DIR}\\" && ./install_cmd.sh"\n'
            '# Wipe the staged install command (which contains the join token).\n'
            'sudo shred -u "${INSTALL_DIR}/install_cmd.sh" 2>/dev/null || sudo rm -f "${INSTALL_DIR}/install_cmd.sh"\n\n'
            "# 3. systemd unit.\n"
            "cat <<UNIT | sudo tee /etc/systemd/system/splunk-edge.service >/dev/null\n"
            "[Unit]\n"
            "Description=Splunk Edge Processor\n"
            "After=network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            'User=${SERVICE_USER}\n'
            'Group=${SERVICE_GROUP}\n'
            'WorkingDirectory=${INSTALL_DIR}/splunk-edge\n'
            'ExecStart=${INSTALL_DIR}/splunk-edge/bin/splunk-edge run\n'
            "Restart=on-failure\n"
            "KillMode=mixed\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
            "UNIT\n\n"
            "sudo systemctl daemon-reload\n"
            "sudo systemctl enable --now splunk-edge.service\n"
            "sudo systemctl status splunk-edge.service --no-pager\n"
            'echo "OK: splunk-edge running on $(hostname)."\n'
        )
    elif instance["mode"] == "nosystemd":
        body = (
            f"INSTALL_DIR={install_dir}\n"
            f"# shellcheck disable=SC2034\n"
            f"TENANT_URL={tenant}\n\n"
            f"{common_install_cmd_block}\n"
            'mkdir -p "${INSTALL_DIR}"\n'
            'install -m 0700 "${INSTALL_CMD_FILE}" "${INSTALL_DIR}/install_cmd.sh"\n'
            '(cd "${INSTALL_DIR}" && ./install_cmd.sh)\n'
            'shred -u "${INSTALL_DIR}/install_cmd.sh" 2>/dev/null || rm -f "${INSTALL_DIR}/install_cmd.sh"\n'
            'nohup ./splunk-edge/bin/splunk-edge run >> ./splunk-edge/var/log/install-splunk-edge.out 2>&1 </dev/null &\n'
            'echo "OK: splunk-edge running in background. PID file in ${INSTALL_DIR}/splunk-edge/var/run/."\n'
        )
    else:  # docker
        body = (
            f"INSTALL_DIR={install_dir}\n"
            f"# shellcheck disable=SC2034\n"
            f"TENANT_URL={tenant}\n\n"
            "# Docker variant per Splunk doc 'Set up an Edge Processor in a Docker container'.\n"
            "# The image name + container env shown below must be replaced with the values\n"
            "# from the operator's tenant install command (Manage instances UI). This\n"
            "# script renders a docker-compose skeleton; replace IMAGE and ENV before\n"
            "# `docker compose up -d`.\n"
            'COMPOSE_FILE="${INSTALL_DIR}/docker-compose.yml"\n'
            'mkdir -p "${INSTALL_DIR}/data"\n'
            'if [[ -f "${COMPOSE_FILE}" ]]; then\n'
            '  echo "INFO: ${COMPOSE_FILE} already exists; not overwriting."\n'
            'else\n'
            '  cat <<COMPOSE > "${COMPOSE_FILE}"\n'
            'version: "3.8"\n'
            "services:\n"
            "  splunk_edge:\n"
            "    # Image and env values come from your tenant install command.\n"
            "    image: splunk/splunk-edge-processor:REPLACE_WITH_TENANT_IMAGE_TAG\n"
            "    container_name: splunk_edge\n"
            "    restart: unless-stopped\n"
            "    network_mode: host\n"
            "    volumes:\n"
            '      - ${INSTALL_DIR}/data:/var/lib/splunk-edge\n'
            "    env_file:\n"
            '      - ${INSTALL_DIR}/.env\n'
            "COMPOSE\n"
            'fi\n\n'
            "# The .env file is operator-supplied (chmod 600) and contains the join token + tenant URL.\n"
            'if [[ ! -s "${INSTALL_DIR}/.env" ]]; then\n'
            '  echo "ERROR: ${INSTALL_DIR}/.env missing. Stage it via write_secret_file.sh with SPLUNK_EDGE_TOKEN=<token> and SPLUNK_EDGE_TENANT_URL=<url>." >&2\n'
            '  exit 1\n'
            'fi\n'
            '(cd "${INSTALL_DIR}" && docker compose up -d)\n'
            'echo "OK: splunk-edge container running."\n'
        )
    return make_script(body)


def render_uninstall(args: argparse.Namespace, instance: dict) -> str:
    install_dir = shell_quote(args.ep_install_dir)
    if instance["mode"] == "systemd":
        body = (
            f"INSTALL_DIR={install_dir}\n"
            "sudo systemctl disable --now splunk-edge.service || true\n"
            "sudo rm -f /etc/systemd/system/splunk-edge.service\n"
            "sudo systemctl daemon-reload\n"
            'sudo rm -rf "${INSTALL_DIR}/splunk-edge"\n'
            'echo "OK: splunk-edge uninstalled."\n'
        )
    elif instance["mode"] == "docker":
        body = (
            f"INSTALL_DIR={install_dir}\n"
            'cd "${INSTALL_DIR}" && docker compose down -v\n'
            'echo "OK: splunk-edge container removed."\n'
        )
    else:
        body = (
            f"INSTALL_DIR={install_dir}\n"
            'pkill -f "splunk-edge/bin/splunk-edge run" || true\n'
            'rm -rf "${INSTALL_DIR}/splunk-edge"\n'
            'echo "OK: splunk-edge process stopped and binaries removed."\n'
        )
    return make_script(body)


def render_apply_objects(args: argparse.Namespace, source_types: list[str], destinations: list[dict], pipelines: list[dict]) -> str:
    tenant = shell_quote(args.ep_tenant_url)
    ep_name = args.ep_name
    # IMPORTANT: As of the published Splunk Edge Processor docs, control-plane
    # operations are primarily UI-driven (Edge Processor → Manage instances).
    # Splunk has not published a stable public REST API base path for EP
    # objects (source types / destinations / pipelines). The variable
    # EP_API_BASE lets the operator point this script at the right base when
    # one is available for their tenant; otherwise the script falls back to
    # printing the rendered payloads and the manual UI steps to apply them.
    body = (
        _EP_LIB_DIR_BLOCK
        + "# shellcheck disable=SC2034\n"
        + f"TENANT_URL={tenant}\n"
        + f'EP_NAME={shell_quote(ep_name)}\n'
        + 'EP_API_BASE="${EP_API_BASE:-}"\n'
        + 'TOKEN_FILE="${EP_API_TOKEN_FILE:-}"\n'
        + 'CONTROL_DIR="$(dirname "$0")"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/credential_helpers.sh"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/edge_processor_helpers.sh"\n\n'
        + 'manual_fallback() {\n'
        + '  cat <<EOM\n'
        + 'NOTE: EP_API_BASE is unset. Splunk has not published a stable public\n'
        + 'REST API base path for Edge Processor control-plane objects, so this\n'
        + 'script will only stage and validate the rendered JSON payloads. To\n'
        + 'apply them manually:\n'
        + '\n'
        + '  1. Open Splunk Cloud Platform -> Edge Processor.\n'
        + '  2. Add each source type from ${CONTROL_DIR}/source-types/.\n'
        + '  3. Add each destination from ${CONTROL_DIR}/destinations/.\n'
        + '  4. Confirm the Edge Processor in ${CONTROL_DIR}/edge-processors/${EP_NAME}.json.\n'
        + '  5. Add each pipeline from ${CONTROL_DIR}/pipelines/<name>.spl2 and apply it to ${EP_NAME}.\n'
        + '\n'
        + 'Once Splunk publishes a control-plane REST API base for your tenant,\n'
        + 'export EP_API_BASE=https://<api-host>/<api-base> and re-run this script\n'
        + 'to apply automatically.\n'
        + 'EOM\n'
        + '}\n\n'
        + 'if [[ -z "${EP_API_BASE}" ]]; then\n'
        + '  manual_fallback\n'
        + '  exit 0\n'
        + 'fi\n\n'
        + 'if [[ -z "${TOKEN_FILE}" || ! -s "${TOKEN_FILE}" ]]; then\n'
        + '  echo "ERROR: EP_API_TOKEN_FILE must point to a non-empty file when EP_API_BASE is set." >&2\n'
        + '  exit 1\n'
        + 'fi\n\n'
        + "# Apply order: source types -> destinations -> EP object -> pipelines -> attach.\n"
        + "# All API calls go through ep_api_call which feeds the Bearer token to\n"
        + "# curl via -K <(...) so it never appears on argv (no `ps` exposure).\n"
    )
    # ep_api_call expects paths under /api/v1/edge-processor/*; the control-
    # plane EP_API_BASE typically already includes that prefix, so we PUT to
    # the operator-supplied base directly via curl built into ep_api_call.
    if source_types:
        body += (
            'shopt -s nullglob\n'
            'for st in "${CONTROL_DIR}"/source-types/*.json; do\n'
            '  name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\\"name\\"])" "${st}")\n'
            '  ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" PUT \\\n'
            '    "/source-types/${name}" --data-binary @"${st}" >/dev/null\n'
            '  echo "OK: source-type ${name} applied"\n'
            'done\n\n'
        )
    if destinations:
        body += (
            'shopt -s nullglob\n'
            'for dest in "${CONTROL_DIR}"/destinations/*.json; do\n'
            '  name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\\"name\\"])" "${dest}")\n'
            '  ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" PUT \\\n'
            '    "/destinations/${name}" --data-binary @"${dest}" >/dev/null\n'
            '  echo "OK: destination ${name} applied"\n'
            'done\n\n'
        )
    body += (
        f'EP_OBJECT="${{CONTROL_DIR}}/edge-processors/{ep_name}.json"\n'
        'if [[ -f "${EP_OBJECT}" ]]; then\n'
        '  ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" PUT \\\n'
        f'    "/edge-processors/{ep_name}" --data-binary @"${{EP_OBJECT}}" >/dev/null\n'
        f'  echo "OK: edge-processor object {ep_name} applied"\n'
        'fi\n\n'
    )
    if pipelines:
        body += (
            'shopt -s nullglob\n'
            'for pipe in "${CONTROL_DIR}"/pipelines/*.json; do\n'
            '  name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\\"name\\"])" "${pipe}")\n'
            '  ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" PUT \\\n'
            '    "/pipelines/${name}" --data-binary @"${pipe}" >/dev/null\n'
            '  echo "OK: pipeline ${name} applied"\n'
            'done\n\n'
            "# Attach all pipelines to the EP object.\n"
            'for pipe in "${CONTROL_DIR}"/pipelines/*.json; do\n'
            '  name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\\"name\\"])" "${pipe}")\n'
            '  ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" POST \\\n'
            f'    "/edge-processors/{ep_name}/pipelines/${{name}}/attach" >/dev/null\n'
            f'  echo "OK: pipeline ${{name}} attached to {ep_name}"\n'
            'done\n'
        )
    return make_script(body)


def render_forwarder_outputs(args: argparse.Namespace, instances: list[dict]) -> str:
    if not instances:
        return ""
    hosts = " ".join(i["host"] for i in instances)
    return f"""# Rendered by splunk-edge-processor-setup. Use a DNS record (e.g. ep.example.com)
# that resolves to all EP instance IPs and reference it here. Forwarders that
# load-balance across multiple EPs MUST use the DNS-driven pattern; otherwise
# pick the first EP host directly.

[tcpout:edge_processor]
server = ep.example.com:9997
# Member EP hosts (for reference): {hosts}

[tcpout]
defaultGroup = edge_processor
"""


def render_validate(args: argparse.Namespace, instances: list[dict], destinations: list[dict], default_destination: str) -> str:
    inst_count = len(instances)
    dest_names = ",".join(sorted(d["name"] for d in destinations)) or "(none)"
    body = (
        _EP_LIB_DIR_BLOCK
        + f'EP_NAME={shell_quote(args.ep_name)}\n'
        + f'DEFAULT_DEST={shell_quote(default_destination)}\n'
        + f'EXPECTED_INSTANCES={inst_count}\n'
        + 'EP_API_BASE="${EP_API_BASE:-}"\n'
        + 'TOKEN_FILE="${EP_API_TOKEN_FILE:-}"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/credential_helpers.sh"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/edge_processor_helpers.sh"\n\n'
        + 'TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)\n'
        + 'AUDIT_DIR="$(dirname "$0")/audit/${TIMESTAMP}"\n'
        + 'mkdir -p "${AUDIT_DIR}"\n'
        + 'chmod 0700 "${AUDIT_DIR}" 2>/dev/null || true\n\n'
        + '# 1. Default-destination guard. Validate fails if no default destination.\n'
        + 'if [[ -z "${DEFAULT_DEST}" ]]; then\n'
        + '  echo "FAIL: No default destination configured. Unprocessed data will be dropped." >&2\n'
        + '  exit 1\n'
        + 'fi\n\n'
        + '# 2. Pull EP object + pipeline status snapshots when an API base is set.\n'
        + '#    Otherwise emit the manual verification checklist (Splunk has not\n'
        + '#    published a stable public REST API base for EP control-plane).\n'
        + 'if [[ -z "${EP_API_BASE}" ]]; then\n'
        + '  cat <<EOM\n'
        + 'PASS (offline): EP ${EP_NAME} render complete (default-destination=${DEFAULT_DEST}).\n'
        + 'Manual checks (Splunk Cloud Platform -> Edge Processor):\n'
        + '  - Confirm ${EXPECTED_INSTANCES} instance(s) report Healthy.\n'
        + '  - Confirm pipelines are Applied to ${EP_NAME}.\n'
        + '  - Confirm destinations are reachable (test inputs).\n'
        + 'Set EP_API_BASE + EP_API_TOKEN_FILE to enable live REST validation.\n'
        + 'EOM\n'
        + '  exit 0\n'
        + 'fi\n\n'
        + 'if [[ -z "${TOKEN_FILE}" || ! -s "${TOKEN_FILE}" ]]; then\n'
        + '  echo "ERROR: EP_API_TOKEN_FILE must point to a non-empty file when EP_API_BASE is set." >&2\n'
        + '  exit 1\n'
        + 'fi\n\n'
        + '# All API calls go through ep_api_call which feeds the Bearer token\n'
        + '# to curl via -K <(...) so it never lands on argv. Output files are\n'
        + '# created with umask 077 by writing through ( umask 077 && ... ).\n'
        + '( umask 077 && ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" GET "/edge-processors/${EP_NAME}" \\\n'
        + '    > "${AUDIT_DIR}/ep-object.json" 2>/dev/null ) \\\n'
        + '    || ( umask 077 && echo "{}" > "${AUDIT_DIR}/ep-object.json" )\n'
        + '( umask 077 && ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" GET "/edge-processors/${EP_NAME}/instances" \\\n'
        + '    > "${AUDIT_DIR}/instances.json" 2>/dev/null ) \\\n'
        + '    || ( umask 077 && echo "{}" > "${AUDIT_DIR}/instances.json" )\n'
        + '( umask 077 && ep_api_call "${EP_API_BASE}" "${TOKEN_FILE}" GET "/edge-processors/${EP_NAME}/pipelines" \\\n'
        + '    > "${AUDIT_DIR}/pipelines.json" 2>/dev/null ) \\\n'
        + '    || ( umask 077 && echo "{}" > "${AUDIT_DIR}/pipelines.json" )\n\n'
        '# 3. Instance health check (best-effort field name parsing).\n'
        'healthy=$(python3 -c "\n'
        'import json, sys\n'
        'data = json.load(open(sys.argv[1])) if sys.argv[1] else {}\n'
        'items = data.get(\\"instances\\", []) if isinstance(data, dict) else []\n'
        '# Different EP API revisions use status / health / healthStatus keys.\n'
        'def is_healthy(i):\n'
        '    for key in (\\"status\\", \\"health\\", \\"healthStatus\\"):\n'
        '        v = i.get(key, \\"\\") if isinstance(i, dict) else \\"\\"\n'
        '        if isinstance(v, str) and v.lower() == \\"healthy\\":\n'
        '            return True\n'
        '    return False\n'
        'print(sum(1 for i in items if is_healthy(i)))\n'
        '" "${AUDIT_DIR}/instances.json" 2>/dev/null || echo 0)\n'
        'if [[ "${healthy}" -lt "${EXPECTED_INSTANCES}" ]]; then\n'
        '  echo "WARN: Only ${healthy}/${EXPECTED_INSTANCES} EP instances Healthy. See ${AUDIT_DIR}/instances.json." >&2\n'
        'fi\n\n'
        f'echo "PASS: EP {args.ep_name} validate complete (default-destination=${{DEFAULT_DEST}}, destinations={dest_names}). Snapshot: ${{AUDIT_DIR}}"\n'
    )
    return make_script(body)


def render_handoff_acs(args: argparse.Namespace, instances: list[dict], destinations: list[dict]) -> dict:
    cloud_features = set()
    for d in destinations:
        if d.get("type") == "s2s":
            cloud_features.add("s2s")
        elif d.get("type") == "hec":
            cloud_features.add("hec")
    payload = {
        "comment": "ACS allowlist plan stub. Replace each instance host with its egress public IP /32 and feed into splunk-cloud-acs-allowlist-setup.",
        "instance_hosts": sorted(i["host"] for i in instances),
        "features": sorted(cloud_features),
    }
    return {"handoffs/acs-allowlist.json": json.dumps(payload, indent=2, sort_keys=True) + "\n"}


def render_metadata(args: argparse.Namespace, instances: list[dict], destinations: list[dict], pipelines: list[dict], source_types: list[str]) -> str:
    return json.dumps(
        {
            "skill": "splunk-edge-processor-setup",
            "ep_control_plane": args.ep_control_plane,
            "ep_tenant_url": args.ep_tenant_url,
            "ep_name": args.ep_name,
            "ep_tls_mode": args.ep_tls_mode,
            "instance_count": len(instances),
            "instance_modes": sorted({i["mode"] for i in instances}),
            "destination_names": sorted(d["name"] for d in destinations),
            "default_destination": args.ep_default_destination,
            "pipeline_names": sorted(p["name"] for p in pipelines),
            "source_type_names": sorted(source_types),
            "target_daily_gb": args.ep_target_daily_gb,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_readme(args: argparse.Namespace, instances: list[dict], destinations: list[dict], pipelines: list[dict]) -> str:
    instance_summary = ", ".join(f"{i['host']} ({i['mode']})" for i in instances) or "(none)"
    dest_summary = ", ".join(d["name"] for d in destinations) or "(none)"
    pipe_summary = ", ".join(p["name"] for p in pipelines) or "(none)"
    return (
        "# Splunk Edge Processor Rendered Assets\n\n"
        f"Control plane: `{args.ep_control_plane}`\n"
        f"Tenant URL: `{args.ep_tenant_url}`\n"
        f"EP name: `{args.ep_name}`\n"
        f"TLS mode: `{args.ep_tls_mode}`\n"
        f"Instances: {len(instances)} ({instance_summary})\n"
        f"Destinations: {dest_summary}\n"
        f"Default destination: `{args.ep_default_destination or '(NOT SET — apply will fail)'}`\n"
        f"Pipelines: {pipe_summary}\n"
        f"Target daily volume: {args.ep_target_daily_gb} GB\n\n"
        "## Files\n\n"
        "- `control-plane/edge-processors/<name>.json` — EP control-plane object.\n"
        "- `control-plane/source-types/<name>.json`.\n"
        "- `control-plane/destinations/<name>.json`.\n"
        "- `control-plane/pipelines/<name>.spl2` and `pipelines/<name>.json`.\n"
        "- `control-plane/apply-objects.sh` — orchestrates POST/PUT.\n"
        "- `host/<host>/install-with-systemd.sh` (or `install-without-systemd.sh` / `install-docker.sh`).\n"
        "- `host/<host>/uninstall.sh`.\n"
        "- `forwarder-templates/outputs.conf`.\n"
        "- `pipelines/templates/{filter,mask,sample,route}.spl2` — Splunk-style starters.\n"
        "- `validate.sh`.\n"
        "- `handoffs/acs-allowlist.json` — promote into `splunk-cloud-acs-allowlist-setup`.\n\n"
        "## Default-destination guard\n\n"
        "Without a default destination, unprocessed data is silently dropped. The\n"
        "renderer requires `--ep-default-destination` to match a destination name.\n"
        "`validate.sh` re-checks this on every run.\n\n"
        "## Next steps\n\n"
        "1. After `apply-objects.sh` succeeds, run `host/<host>/install-with-systemd.sh` on each instance host.\n"
        "2. Promote `handoffs/acs-allowlist.json` into `splunk-cloud-acs-allowlist-setup` so destinations on Splunk Cloud become reachable.\n"
        "3. If forwarders need to send through this EP, deploy `forwarder-templates/outputs.conf` to each forwarder.\n"
    )


def render_all(args: argparse.Namespace) -> dict:
    instances = parse_instances(args.ep_instances)
    destinations = parse_destinations(args.ep_destinations)
    pipelines = parse_pipelines(args.ep_pipelines)
    source_types = csv_list(args.ep_source_types)

    # Default-destination guard at render time.
    if destinations and not args.ep_default_destination:
        die("--ep-default-destination is required when destinations are defined; without it, unprocessed data is dropped.")
    if args.ep_default_destination and not any(d["name"] == args.ep_default_destination for d in destinations):
        die(f"--ep-default-destination {args.ep_default_destination!r} does not match any destination name in --ep-destinations.")

    output_dir = Path(args.output_dir).expanduser().resolve()
    files = []

    write_file(output_dir / "README.md", render_readme(args, instances, destinations, pipelines))
    files.append("README.md")
    write_file(output_dir / "metadata.json", render_metadata(args, instances, destinations, pipelines, source_types))
    files.append("metadata.json")
    write_file(output_dir / "validate.sh", render_validate(args, instances, destinations, args.ep_default_destination), executable=True)
    files.append("validate.sh")

    # Control-plane EP object.
    write_file(output_dir / f"control-plane/edge-processors/{args.ep_name}.json", render_ep_object(args))
    files.append(f"control-plane/edge-processors/{args.ep_name}.json")

    # Source types.
    for st in source_types:
        write_file(output_dir / f"control-plane/source-types/{st}.json", render_source_type(st))
        files.append(f"control-plane/source-types/{st}.json")

    # Destinations.
    dest_by_name = {d["name"]: d for d in destinations}
    for dest in destinations:
        write_file(output_dir / f"control-plane/destinations/{dest['name']}.json", render_destination(dest))
        files.append(f"control-plane/destinations/{dest['name']}.json")

    # Pipelines.
    for pipe in pipelines:
        write_file(output_dir / f"control-plane/pipelines/{pipe['name']}.json", render_pipeline_payload(pipe))
        write_file(output_dir / f"control-plane/pipelines/{pipe['name']}.spl2", render_pipeline_spl2(pipe, dest_by_name.get(pipe["destination"])))
        files.append(f"control-plane/pipelines/{pipe['name']}.json")
        files.append(f"control-plane/pipelines/{pipe['name']}.spl2")

    # Pipeline starter templates.
    for name, content in render_pipeline_templates().items():
        write_file(output_dir / f"pipelines/templates/{name}", content)
        files.append(f"pipelines/templates/{name}")

    # Apply orchestrator.
    write_file(output_dir / "control-plane/apply-objects.sh", render_apply_objects(args, source_types, destinations, pipelines), executable=True)
    files.append("control-plane/apply-objects.sh")

    # Per-instance install + uninstall.
    for inst in instances:
        host = inst["host"]
        mode = inst["mode"]
        if mode == "systemd":
            install_name = "install-with-systemd.sh"
        elif mode == "nosystemd":
            install_name = "install-without-systemd.sh"
        else:
            install_name = "install-docker.sh"
        write_file(output_dir / f"host/{host}/{install_name}", render_instance_install(args, inst), executable=True)
        files.append(f"host/{host}/{install_name}")
        write_file(output_dir / f"host/{host}/uninstall.sh", render_uninstall(args, inst), executable=True)
        files.append(f"host/{host}/uninstall.sh")

    # Forwarder template (only when there are instances).
    fwd_content = render_forwarder_outputs(args, instances)
    if fwd_content:
        write_file(output_dir / "forwarder-templates/outputs.conf", fwd_content)
        files.append("forwarder-templates/outputs.conf")

    # ACS allowlist hand-off stub.
    for rel, content in render_handoff_acs(args, instances, destinations).items():
        write_file(output_dir / rel, content)
        files.append(rel)

    return {"render_dir": str(output_dir), "files": sorted(files)}


def main() -> None:
    args = parse_args()
    if args.dry_run:
        instances = parse_instances(args.ep_instances)
        destinations = parse_destinations(args.ep_destinations)
        pipelines = parse_pipelines(args.ep_pipelines)
        payload = {"instances": instances, "destinations": destinations, "pipelines": pipelines}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return
    result = render_all(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(result['files'])} EP asset(s) to {result['render_dir']}")
        for name in result["files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
