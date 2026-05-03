#!/usr/bin/env python3
"""Render Splunk SOAR setup assets for on-prem single, on-prem cluster, and cloud."""

from __future__ import annotations

import argparse
import json
import shlex
import stat
from pathlib import Path


VALID_PLATFORMS = ("onprem-single", "onprem-cluster", "cloud")
VALID_FIPS = ("auto", "require", "disable")
VALID_RUNTIMES = ("docker", "podman")
VALID_IMAGE_SOURCES = ("dockerhub", "tarball")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render Splunk SOAR assets.")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--soar-platform", choices=VALID_PLATFORMS, default="onprem-single")
    p.add_argument("--soar-home", default="/opt/soar")
    p.add_argument("--soar-https-port", default="8443")
    p.add_argument("--soar-port-forward", choices=("true", "false"), default="false")
    p.add_argument("--soar-hostname", default="")
    p.add_argument("--soar-tgz", default="")
    p.add_argument("--soar-fips", choices=VALID_FIPS, default="auto")
    p.add_argument("--soar-hosts", default="")
    p.add_argument("--soar-ssh-user", default="splunk")
    p.add_argument("--external-pg", default="")
    p.add_argument("--external-gluster", default="")
    p.add_argument("--external-es", default="")
    p.add_argument("--load-balancer", default="")
    p.add_argument("--soar-tenant-url", default="")
    p.add_argument("--soar-cloud-admin-email", default="")
    p.add_argument("--automation-broker", default="")
    p.add_argument(
        "--splunk-side-apps",
        # Splunkbase 3411 ("Splunk App for SOAR Export", folder name `phantom`)
        # is the modern packaging of the legacy "Splunk Add-on for Phantom"
        # (TA-phantom). There is no separate ta_phantom package on Splunkbase;
        # the export app covers both surfaces.
        default="app_for_soar=true,app_for_soar_export=true",
    )
    p.add_argument("--es-integration-readiness", choices=("true", "false"), default="true")
    p.add_argument("--auth-file", default="")
    p.add_argument("--ca-cert-file", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list:
    return [item.strip() for item in value.split(",") if item.strip()]


def kv_dict(value: str) -> dict:
    if not value.strip():
        return {}
    out = {}
    for kv in csv_list(value):
        if "=" not in kv:
            die(f"Expected key=value, got {kv!r}")
        k, v = kv.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


# Runtime locator for skills/shared/lib so the rendered SOAR scripts can
# source soar_helpers.sh (which keeps the SOAR ph-auth-token and
# soar_local_admin password off curl's argv via -K <(...) / --netrc-file).
# Mirrors the pattern used by the license, indexer-cluster, and EP renderers.
_SOAR_LIB_DIR_BLOCK = (
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


def render_onprem_single(args: argparse.Namespace) -> dict:
    soar_home = shell_quote(args.soar_home)
    https_port = shell_quote(args.soar_https_port)
    soar_tgz = shell_quote(args.soar_tgz)
    port_forward = "true" if args.soar_port_forward == "true" else "false"
    fips = args.soar_fips

    prepare_body = (
        f"SOAR_HOME={soar_home}\n"
        f"HTTPS_PORT={https_port}\n"
        f"SOAR_TGZ={soar_tgz}\n"
        f"PORT_FORWARD={port_forward}\n"
        f"FIPS_MODE={fips}\n\n"
        'if [[ ! -s "${SOAR_TGZ}" ]]; then\n'
        '  echo "ERROR: SOAR TGZ missing or empty: ${SOAR_TGZ}" >&2\n'
        '  exit 1\n'
        'fi\n\n'
        'if ! systemctl status firewalld >/dev/null 2>&1; then\n'
        '  echo "WARNING: firewalld not running; SOAR install requires firewalld." >&2\n'
        '  sudo systemctl enable firewalld\n'
        '  sudo systemctl start firewalld\n'
        'fi\n'
        'sudo firewall-cmd --permanent --zone public --add-port "${HTTPS_PORT}/tcp" >/dev/null\n'
        'sudo firewall-cmd --reload >/dev/null\n\n'
        'sudo localectl set-locale LANG=en_US.UTF-8 || true\n'
        'sudo localectl set-keymap us || true\n\n'
        'if [[ -r /proc/sys/crypto/fips_enabled ]]; then\n'
        '  fips_state=$(cat /proc/sys/crypto/fips_enabled)\n'
        'else\n'
        '  fips_state=0\n'
        'fi\n'
        'case "${FIPS_MODE}" in\n'
        '  require)\n'
        '    if [[ "${fips_state}" != "1" ]]; then\n'
        '      echo "ERROR: --soar-fips require but kernel is not in FIPS mode." >&2\n'
        '      exit 1\n'
        '    fi\n'
        '    ;;\n'
        'esac\n\n'
        'mkdir -p "${SOAR_HOME}"\n'
        'sudo chown "$(whoami):$(whoami)" "${SOAR_HOME}" || true\n'
        'tar -xzf "${SOAR_TGZ}" -C "${SOAR_HOME}"\n'
        'cd "${SOAR_HOME}/splunk-soar"\n\n'
        'PREPARE_ARGS=(--splunk-soar-home "${SOAR_HOME}" --https-port "${HTTPS_PORT}")\n'
        'if [[ "${PORT_FORWARD}" == "true" ]]; then\n'
        '  PREPARE_ARGS+=(--port-forward)\n'
        'fi\n'
        'sudo ./soar-prepare-system "${PREPARE_ARGS[@]}"\n\n'
        'echo "OK: soar-prepare-system complete. Run install-soar.sh next as the unprivileged SOAR user."\n'
    )

    install_body = (
        f"SOAR_HOME={soar_home}\n"
        f"HTTPS_PORT={https_port}\n\n"
        'cd "${SOAR_HOME}/splunk-soar"\n'
        './soar-install --splunk-soar-home "${SOAR_HOME}" --https-port "${HTTPS_PORT}"\n'
        'echo "OK: SOAR install complete. Visit https://$(hostname):${HTTPS_PORT}/ to finish first-time login."\n'
    )

    checklist = (
        "# Splunk SOAR (On-prem single) Post-install Checklist\n\n"
        f"1. Visit `https://{args.soar_hostname or '<soar-host>'}:{args.soar_https_port}/`.\n"
        "2. Complete the first-time onboarding tour (admin password reset, EULA).\n"
        "3. Mint an `automation` REST user via `cloud/automation-user.sh`.\n"
        "4. Configure SAML / LDAP / OAuth in Splunk SOAR -> Administration -> User Management.\n"
        "5. Install Splunk-side apps:\n"
        "   ```bash\n"
        "   bash splunk-side/install-app-for-soar.sh\n"
        "   bash splunk-side/install-app-for-soar-export.sh\n"
        "   bash splunk-side/configure-phantom-endpoint.sh\n"
        "   ```\n"
        "6. Run `validate.sh` to confirm REST endpoints are reachable.\n"
    )

    return {
        "prepare-system.sh": make_script(prepare_body),
        "install-soar.sh": make_script(install_body),
        "post-install-checklist.md": checklist,
    }


def render_onprem_cluster(args: argparse.Namespace) -> dict:
    hosts = csv_list(args.soar_hosts)
    soar_ssh = shell_quote(args.soar_ssh_user)
    soar_home = shell_quote(args.soar_home)
    https_port = shell_quote(args.soar_https_port)
    soar_tgz = shell_quote(args.soar_tgz)
    pg = kv_dict(args.external_pg)
    es_hosts = csv_list(args.external_es)
    gluster_hosts = csv_list(args.external_gluster)
    lb = args.load_balancer or "lb01"

    out = {}

    hosts_q = " ".join(shell_quote(h) for h in hosts) or shell_quote("soar01")
    cluster_body = (
        f"SOAR_HOME={soar_home}\n"
        f"HTTPS_PORT={https_port}\n"
        f"SOAR_TGZ={soar_tgz}\n"
        f"SSH_USER={soar_ssh}\n\n"
        f'for host in {hosts_q}; do\n'
        '  scp -o StrictHostKeyChecking=accept-new "${SOAR_TGZ}" "${SSH_USER}@${host}:/tmp/soar.tgz"\n'
        "  ssh -o StrictHostKeyChecking=accept-new \"${SSH_USER}@${host}\" \"\n"
        "    set -euo pipefail\n"
        "    sudo mkdir -p ${SOAR_HOME}\n"
        "    sudo chown ${SSH_USER}:${SSH_USER} ${SOAR_HOME}\n"
        "    tar -xzf /tmp/soar.tgz -C ${SOAR_HOME}\n"
        "    cd ${SOAR_HOME}/splunk-soar\n"
        "    sudo ./soar-prepare-system --splunk-soar-home ${SOAR_HOME} --https-port ${HTTPS_PORT}\n"
        "    ./soar-install --splunk-soar-home ${SOAR_HOME} --https-port ${HTTPS_PORT}\n"
        "    cd ${SOAR_HOME}/bin\n"
        "    phenv python make_cluster_node.pyc\n"
        "  \"\n"
        "done\n"
        'echo "OK: cluster nodes provisioned. Configure load balancer next via external-services/haproxy.cfg."\n'
    )
    out["make-cluster-node.sh"] = make_script(cluster_body)

    primary = hosts[0] if hosts else "<primary-host>"
    backup_body = (
        f"SOAR_HOME={soar_home}\n"
        f'PRIMARY_HOST="{primary}"\n'
        f"SSH_USER={soar_ssh}\n"
        'ssh -o StrictHostKeyChecking=accept-new "${SSH_USER}@${PRIMARY_HOST}" "\n'
        "  cd ${SOAR_HOME}/bin\n"
        "  phenv python backup.pyc --all\n"
        '"\n'
        'echo "OK: backup complete. Snapshot is in ${SOAR_HOME}/data/phantom_backups/ on ${PRIMARY_HOST}."\n'
    )
    out["backup.sh"] = make_script(backup_body)

    restore_body = (
        f"SOAR_HOME={soar_home}\n"
        f'PRIMARY_HOST="{primary}"\n'
        f"SSH_USER={soar_ssh}\n"
        'BACKUP_PATH="${BACKUP_PATH:?set BACKUP_PATH=/path/to/phantom_backup_*.tgz on the primary host}"\n'
        'ssh -o StrictHostKeyChecking=accept-new "${SSH_USER}@${PRIMARY_HOST}" "\n'
        "  cd ${SOAR_HOME}/bin\n"
        "  phenv python ibackup.pyc --restore --backup ${BACKUP_PATH}\n"
        '"\n'
        'echo "OK: restore complete. Verify cluster health via /rest/cluster_node."\n'
    )
    out["restore.sh"] = make_script(restore_body)

    pg_mode = pg.get("mode", "local")
    pg_host = pg.get("host", "<db-host>")
    pg_port = pg.get("port", "5432")

    if pg_mode == "rds":
        out["external-services/postgres-rds.tf"] = (
            "# Sample Terraform for AWS RDS PostgreSQL 15.x for SOAR.\n"
            'resource "aws_db_instance" "soar_postgres" {\n'
            '  identifier              = "soar-postgres"\n'
            '  engine                  = "postgres"\n'
            '  engine_version          = "15.3"\n'
            '  instance_class          = "db.t3.large"\n'
            "  allocated_storage       = 500\n"
            "  max_allocated_storage   = 1000\n"
            '  db_name                 = "phantom"\n'
            '  username                = "postgres"\n'
            "  password                = var.postgres_master_password\n"
            f"  port                    = {pg_port}\n"
            "  publicly_accessible     = false\n"
            "  vpc_security_group_ids  = var.security_group_ids\n"
            "  db_subnet_group_name    = var.db_subnet_group_name\n"
            '  parameter_group_name    = "default.postgres15"\n'
            "  backup_retention_period = 7\n"
            "  storage_encrypted       = true\n"
            "  skip_final_snapshot     = false\n"
            "  apply_immediately       = false\n"
            "}\n\n"
            "# Provision the pgbouncer user after RDS comes up:\n"
            f"#   psql --host {pg_host} --port {pg_port} --username postgres --dbname phantom \\\n"
            "#     --command \"CREATE ROLE pgbouncer WITH PASSWORD '<password>' login;\"\n"
            f"#   psql --host {pg_host} --port {pg_port} --username postgres --dbname phantom \\\n"
            "#     --command \"GRANT rds_superuser TO pgbouncer;\"\n"
        )
    else:
        # Local PostgreSQL install. The pgbouncer password is read from a
        # chmod 600 file and fed to psql via a stdin script so it never
        # appears in `psql -c` argv (visible in `ps`).
        local_pg_body = (
            "# Local PostgreSQL 15 install for SOAR cluster.\n"
            "sudo dnf install -y postgresql15-server postgresql15-contrib\n"
            "sudo /usr/pgsql-15/bin/postgresql-15-setup initdb\n"
            "sudo systemctl enable postgresql-15\n"
            "sudo systemctl start postgresql-15\n\n"
            'PGB_PW_FILE="${PGBOUNCER_PASSWORD_FILE:-/tmp/pgbouncer_password}"\n'
            'if [[ ! -s "${PGB_PW_FILE}" ]]; then\n'
            '  echo "ERROR: pgbouncer password file is empty: ${PGB_PW_FILE}" >&2\n'
            '  exit 1\n'
            'fi\n\n'
            'sudo -u postgres psql -d postgres <<\'PSQL\'\n'
            'CREATE DATABASE phantom;\n'
            'PSQL\n\n'
            "# Build the CREATE USER ... PASSWORD ... statement in shell, then\n"
            "# pipe to psql via stdin. The password value is in the shell's\n"
            "# memory and the SQL stream, but not in any process's argv.\n"
            "# psql --no-readline is set so the password is not echoed to a\n"
            "# history file. SQL-quote any embedded single quotes in the\n"
            "# password to keep the statement well-formed.\n"
            'pg_pw_value="$(cat "${PGB_PW_FILE}")"\n'
            'pg_pw_quoted="${pg_pw_value//\\\'/\\\'\\\'}"\n'
            'unset pg_pw_value\n'
            'printf "CREATE USER pgbouncer PASSWORD \'%s\';\\n" "${pg_pw_quoted}" \\\n'
            '  | sudo -u postgres psql --no-readline -d postgres -v ON_ERROR_STOP=1\n'
            'unset pg_pw_quoted\n'
            'echo "OK: local PostgreSQL ready for SOAR cluster."\n'
        )
        out["external-services/postgres-local.sh"] = make_script(local_pg_body)

    gluster_default = ",".join(gluster_hosts) if gluster_hosts else "gluster01,gluster02"
    gluster_body = (
        "# Sample GlusterFS volume creation for SOAR cluster. Run as root.\n"
        f'GLUSTER_PEERS="{gluster_default}"\n'
        'VOLUME_NAME="${VOLUME_NAME:-soar_data}"\n'
        'BRICK_DIR="${BRICK_DIR:-/data/glusterfs/${VOLUME_NAME}/brick1}"\n'
        'for peer in ${GLUSTER_PEERS//,/ }; do\n'
        '  sudo gluster peer probe "${peer}" || true\n'
        'done\n'
        'sudo mkdir -p "${BRICK_DIR}"\n'
        '# Build the brick list as an array so each peer:brick pair is a single arg.\n'
        'BRICKS=()\n'
        'for p in ${GLUSTER_PEERS//,/ }; do\n'
        '  BRICKS+=("${p}:${BRICK_DIR}")\n'
        'done\n'
        'sudo gluster volume create "${VOLUME_NAME}" replica 2 transport tcp \\\n'
        '  "${BRICKS[@]}" \\\n'
        '  force\n'
        'sudo gluster volume start "${VOLUME_NAME}"\n'
        'echo "OK: gluster volume ${VOLUME_NAME} ready. Mount it on each SOAR node."\n'
    )
    out["external-services/gluster-volume.sh"] = make_script(gluster_body)

    es_seed = ', '.join(f'"{h}"' for h in es_hosts) if es_hosts else '"es01", "es02", "es03"'
    out["external-services/elasticsearch.yml"] = (
        "# Sample Elasticsearch config for SOAR cluster.\n"
        "cluster.name: soar-cluster\n"
        f"discovery.seed_hosts: [{es_seed}]\n"
        f"cluster.initial_master_nodes: [{es_seed}]\n"
        "xpack.security.enabled: true\n"
        "xpack.security.transport.ssl.enabled: true\n"
    )

    server_lines = "\n".join(f"  server soar{i+1} {h}:{args.soar_https_port} check" for i, h in enumerate(hosts))
    if not server_lines:
        server_lines = f"  server soar1 soar01:{args.soar_https_port} check"
    out["external-services/haproxy.cfg"] = (
        "# Sample HAProxy config for SOAR cluster.\n"
        "global\n"
        "  log /dev/log local0\n"
        "  daemon\n"
        "defaults\n"
        "  log     global\n"
        "  mode    tcp\n"
        "  option  tcplog\n"
        "  timeout connect 5s\n"
        "  timeout client  1m\n"
        "  timeout server  1m\n\n"
        "frontend soar_https\n"
        f"  bind {lb}:{args.soar_https_port}\n"
        "  default_backend soar_nodes\n\n"
        "backend soar_nodes\n"
        "  balance leastconn\n"
        f"{server_lines}\n"
    )

    return out


def render_cloud(args: argparse.Namespace) -> dict:
    out = {}
    tenant = args.soar_tenant_url
    admin = args.soar_cloud_admin_email or "<admin-email>"

    out["onboarding-checklist.md"] = (
        "# Splunk SOAR (Cloud) Onboarding Checklist\n\n"
        f"1. Accept the Splunk SOAR (Cloud) tenant invite from Splunk ({admin}).\n"
        f"2. Visit `{tenant or 'https://<tenant-host>/soar'}/login` and complete first-time onboarding.\n"
        "3. Run `cloud/jwt-token-helper.sh` to capture a long-lived JWT into `/tmp/soar_api_token` (chmod 600).\n"
        "4. Run `cloud/automation-user.sh` to mint a dedicated `automation` REST user.\n"
        "5. Apply the SOAR Cloud IP allowlist via `cloud/apply-allowlist.sh` (NOT the Splunk Cloud ACS allowlist).\n"
        "6. To reach private network resources, install Automation Broker via `automation-broker/install.sh`.\n"
        "7. Install Splunk-side apps via `splunk-side/install-*.sh` and configure ES via\n"
        "   `splunk-side/configure-phantom-endpoint.sh`.\n"
    )

    jwt_body = (
        f'TENANT_URL="{tenant or "https://<tenant-host>/soar"}"\n'
        'TOKEN_FILE="${SOAR_API_TOKEN_FILE:-/tmp/soar_api_token}"\n\n'
        "cat <<EOM\n"
        'Open ${TENANT_URL}/admin/user_management?type=automation in your browser.\n'
        "Create or select an 'automation' user, then use 'Generate Token' to mint a\n"
        'long-lived JWT. Paste the JWT below; it will be written to ${TOKEN_FILE}\n'
        "with chmod 600 and not echoed.\n"
        "EOM\n"
        'read -rs -p "JWT: " jwt\n'
        "echo\n"
        'if [[ -z "${jwt}" ]]; then\n'
        '  echo "ERROR: empty JWT entered." >&2\n'
        '  exit 1\n'
        'fi\n'
        "umask 077\n"
        'mkdir -p "$(dirname "${TOKEN_FILE}")"\n'
        'printf "%s" "${jwt}" > "${TOKEN_FILE}"\n'
        'chmod 600 "${TOKEN_FILE}"\n'
        'echo "OK: JWT written to ${TOKEN_FILE}"\n'
    )
    out["jwt-token-helper.sh"] = make_script(jwt_body)

    out["ip-allowlist.json"] = json.dumps(
        {
            "tenant_url": tenant,
            "subnets_ipv4": [],
            "subnets_ipv6": [],
            "comment": "Replace subnets_ipv4 / subnets_ipv6 with your egress CIDRs and run apply-allowlist.sh.",
        },
        indent=2,
        sort_keys=True,
    ) + "\n"

    # apply-allowlist and automation-user both source soar_helpers.sh so the
    # SOAR ph-auth-token / soar_local_admin password are fed to curl via
    # process substitution (never via -H or -u on argv).
    apply_allow_body = (
        _SOAR_LIB_DIR_BLOCK
        + f'TENANT_URL="{tenant or "https://<tenant-host>/soar"}"\n'
        + 'TOKEN_FILE="${SOAR_API_TOKEN_FILE:-/tmp/soar_api_token}"\n'
        + 'PLAN_FILE="$(dirname "$0")/ip-allowlist.json"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/credential_helpers.sh"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/soar_helpers.sh"\n\n'
        + 'if [[ ! -s "${TOKEN_FILE}" ]]; then\n'
        + '  echo "ERROR: SOAR API token missing: ${TOKEN_FILE}" >&2\n'
        + '  exit 1\n'
        + 'fi\n\n'
        + "# SOAR Cloud allowlist managed via SOAR tenant API (NOT ACS).\n"
        + 'soar_rest_call "${TENANT_URL}" "${TOKEN_FILE}" PUT \\\n'
        + '  /rest/system_settings/ip_allowlist \\\n'
        + '  --data-binary @"${PLAN_FILE}"\n'
        + 'echo "OK: SOAR Cloud allowlist applied. Run /rest/system_info to confirm."\n'
    )
    out["apply-allowlist.sh"] = make_script(apply_allow_body)

    auto_user_body = (
        _SOAR_LIB_DIR_BLOCK
        + f'TENANT_URL="{tenant or "https://<tenant-host>/soar"}"\n'
        + 'ADMIN_PW_FILE="${SOAR_ADMIN_PASSWORD_FILE:-/tmp/soar_admin_password}"\n'
        + 'USERNAME="${SOAR_AUTOMATION_USER:-automation_splunk}"\n'
        + 'NEW_TOKEN_FILE="${NEW_TOKEN_FILE:-/tmp/soar_automation_token}"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/credential_helpers.sh"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/soar_helpers.sh"\n\n'
        + 'if [[ ! -s "${ADMIN_PW_FILE}" ]]; then\n'
        + '  echo "ERROR: SOAR admin password file empty: ${ADMIN_PW_FILE}" >&2\n'
        + '  exit 1\n'
        + 'fi\n\n'
        + "# soar_create_automation_user wraps the 3-step SOAR REST flow\n"
        + "# (create user -> look up id -> mint token) using --netrc-file via\n"
        + "# process substitution. The admin password never lands on argv,\n"
        + "# response bodies are mktemp'd at 0600 and unlinked, and the new\n"
        + "# automation token is written under umask 077 with chmod 600.\n"
        + 'soar_create_automation_user "${TENANT_URL}" "${ADMIN_PW_FILE}" "${USERNAME}" "${NEW_TOKEN_FILE}"\n'
    )
    out["automation-user.sh"] = make_script(auto_user_body)

    return out


def render_automation_broker(args: argparse.Namespace) -> dict:
    cfg = kv_dict(args.automation_broker)
    if not cfg:
        return {}
    runtime = cfg.get("runtime", "docker")
    if runtime not in VALID_RUNTIMES:
        die(f"automation_broker runtime must be docker or podman: {runtime!r}")
    image_source = cfg.get("image_source", "dockerhub")
    if image_source not in VALID_IMAGE_SOURCES:
        die(f"automation_broker image_source must be dockerhub or tarball: {image_source!r}")

    out = {}
    compose_yaml = (
        'version: "3.8"\n'
        "services:\n"
        "  automation_broker:\n"
        "    image: splunk/soar-automation-broker:latest\n"
        "    container_name: soar_automation_broker\n"
        "    restart: unless-stopped\n"
        "    network_mode: host\n"
        "    environment:\n"
        "      - SOAR_TENANT_URL\n"
        "      - SOAR_AUTOMATION_TOKEN\n"
        "    volumes:\n"
        "      - ./broker_data:/var/lib/automation_broker\n"
        "      - ./trusted_cas:/etc/ssl/certs/automation_broker\n"
        "    healthcheck:\n"
        '      test: ["CMD", "/usr/local/bin/automation_broker_healthcheck.sh"]\n'
        "      interval: 30s\n"
        "      timeout: 10s\n"
        "      retries: 3\n"
    )
    if runtime == "docker":
        out["docker-compose.yml"] = compose_yaml
        compose_file = "docker-compose.yml"
        compose_cmd = "docker compose"
    else:
        out["podman-compose.yml"] = compose_yaml
        compose_file = "podman-compose.yml"
        compose_cmd = "podman compose"

    # When image_source != tarball at render time, omit the tarball-load
    # branch entirely (avoids SC2050 constant-expression warning at runtime).
    tarball_block = ""
    if image_source == "tarball":
        tarball_block = (
            "# Image source: tarball (air-gapped install).\n"
            'TARBALL_PATH="${AUTOMATION_BROKER_TARBALL:?set AUTOMATION_BROKER_TARBALL=/path/to/image.tar}"\n'
            f'{runtime} load -i "${{TARBALL_PATH}}"\n\n'
        )
    install_body = (
        '# SOAR_TENANT_URL must be in the calling environment so docker compose\n'
        '# can read it via env_file passthrough. Same for SOAR_AUTOMATION_TOKEN.\n'
        ': "${SOAR_TENANT_URL:?set SOAR_TENANT_URL=https://...}"\n'
        'TOKEN_FILE="${SOAR_AUTOMATION_TOKEN_FILE:?set SOAR_AUTOMATION_TOKEN_FILE=/path/to/token}"\n'
        'if [[ ! -s "${TOKEN_FILE}" ]]; then\n'
        '  echo "ERROR: token file missing: ${TOKEN_FILE}" >&2\n'
        '  exit 1\n'
        'fi\n'
        'SOAR_AUTOMATION_TOKEN="$(cat "${TOKEN_FILE}")"\n'
        'export SOAR_AUTOMATION_TOKEN\n'
        'export SOAR_TENANT_URL\n\n'
        "mkdir -p broker_data trusted_cas\n\n"
        f"{tarball_block}"
        f'{compose_cmd} -f "$(dirname "$0")/{compose_file}" up -d\n'
        f'echo "OK: Automation Broker container running. Confirm via {runtime} ps."\n'
    )
    out["install.sh"] = make_script(install_body)

    add_ca_body = (
        'CA_CERT="${CA_CERT:?set CA_CERT=/path/to/ca.pem}"\n'
        'if [[ ! -s "${CA_CERT}" ]]; then\n'
        '  echo "ERROR: CA certificate missing: ${CA_CERT}" >&2\n'
        '  exit 1\n'
        'fi\n'
        "mkdir -p trusted_cas\n"
        'cp "${CA_CERT}" trusted_cas/\n'
        f'{runtime} compose restart automation_broker\n'
        'echo "OK: CA certificate added to Automation Broker trust store."\n'
    )
    out["add-ca-certificate.sh"] = make_script(add_ca_body)

    preflight_body = (
        "cpu_cores=$(nproc)\n"
        "mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)\n"
        "mem_gb=$((mem_kb / 1024 / 1024))\n"
        "disk_free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')\n\n"
        "errors=0\n"
        'if [[ "${cpu_cores}" -lt 4 ]]; then\n'
        '  echo "FAIL: Automation Broker needs >=4 CPU cores, got ${cpu_cores}" >&2\n'
        "  errors=$((errors + 1))\n"
        'fi\n'
        'if [[ "${mem_gb}" -lt 8 ]]; then\n'
        '  echo "FAIL: Automation Broker needs >=8 GB RAM, got ${mem_gb} GB" >&2\n'
        "  errors=$((errors + 1))\n"
        'fi\n'
        'if [[ "${disk_free_gb}" -lt 20 ]]; then\n'
        '  echo "FAIL: Automation Broker needs >=20 GB free disk, got ${disk_free_gb} GB" >&2\n'
        "  errors=$((errors + 1))\n"
        'fi\n'
        f'if ! command -v {runtime} >/dev/null 2>&1; then\n'
        f'  echo "FAIL: {runtime} runtime is not installed." >&2\n'
        "  errors=$((errors + 1))\n"
        'fi\n'
        'if [[ -r /proc/sys/crypto/fips_enabled ]]; then\n'
        '  fips=$(cat /proc/sys/crypto/fips_enabled)\n'
        '  if [[ "${fips}" == "1" ]]; then\n'
        '    echo "INFO: Host kernel is in FIPS mode; Automation Broker will run FIPS-compliant."\n'
        '  fi\n'
        'fi\n'
        'if [[ "${errors}" -gt 0 ]]; then\n'
        '  exit 1\n'
        'fi\n'
        'echo "PASS: Automation Broker preflight"\n'
    )
    out["preflight.sh"] = make_script(preflight_body)

    return out


def render_splunk_side(args: argparse.Namespace) -> dict:
    apps = kv_dict(args.splunk_side_apps)
    out = {}
    project_root = Path(__file__).resolve().parents[3]
    app_install = project_root / "skills/splunk-app-install/scripts/install_app.sh"
    app_install_q = shell_quote(app_install)
    es_config = project_root / "skills/splunk-enterprise-security-config/scripts/setup.sh"
    es_config_q = shell_quote(es_config)

    def install_app_script(splunkbase_id: str, label: str) -> str:
        # Calls the real splunk-app-install installer with the documented
        # `--source splunkbase --app-id <ID>` flags.
        body = (
            f"# Installs '{label}' (Splunkbase {splunkbase_id}) via splunk-app-install.\n"
            f"APP_INSTALL={app_install_q}\n"
            f"SPLUNKBASE_ID={splunkbase_id}\n"
            f'APP_LABEL="{label}"\n\n'
            'if [[ ! -x "${APP_INSTALL}" ]]; then\n'
            '  echo "ERROR: splunk-app-install installer missing or not executable: ${APP_INSTALL}" >&2\n'
            '  exit 1\n'
            'fi\n\n'
            'bash "${APP_INSTALL}" --source splunkbase --app-id "${SPLUNKBASE_ID}"\n'
            'echo "OK: ${APP_LABEL} (Splunkbase ${SPLUNKBASE_ID}) install complete."\n'
        )
        return make_script(body)

    if apps.get("app_for_soar", "true") == "true":
        out["install-app-for-soar.sh"] = install_app_script("6361", "Splunk App for SOAR")
    if apps.get("app_for_soar_export", "true") == "true":
        out["install-app-for-soar-export.sh"] = install_app_script("3411", "Splunk App for SOAR Export")

    # ES <-> SOAR wiring goes through a YAML spec consumed by
    # splunk-enterprise-security-config --spec --apply. We render a
    # ready-to-edit YAML alongside the wrapper script so operators can review
    # the integration block before apply.
    spec_yaml = (
        "# Rendered by splunk-soar-setup. Review and edit before --apply.\n"
        "# splunk-enterprise-security-config consumes this spec via --spec.\n"
        "integrations:\n"
        "  soar:\n"
        "    phantom_endpoint_env: SOAR_TENANT_URL\n"
        "    phantom_token_file_env: SOAR_AUTOMATION_TOKEN_FILE\n"
        "    notable_event_forwarding: true\n"
    )
    out["es-soar-integration.yaml"] = spec_yaml

    es_body = (
        "# Wires SOAR <-> ES via splunk-enterprise-security-config --spec.\n"
        "# The spec lives next to this script as es-soar-integration.yaml.\n"
        f"ES_CONFIG={es_config_q}\n"
        'SOAR_TENANT_URL="${SOAR_TENANT_URL:?set SOAR_TENANT_URL=https://...}"\n'
        'TOKEN_FILE="${SOAR_AUTOMATION_TOKEN_FILE:?set SOAR_AUTOMATION_TOKEN_FILE=/path/to/token}"\n'
        'SPEC_PATH="$(dirname "$0")/es-soar-integration.yaml"\n\n'
        'if [[ ! -s "${TOKEN_FILE}" ]]; then\n'
        '  echo "ERROR: SOAR automation token file missing or empty: ${TOKEN_FILE}" >&2\n'
        '  exit 1\n'
        'fi\n'
        'if [[ ! -x "${ES_CONFIG}" ]]; then\n'
        '  echo "WARNING: splunk-enterprise-security-config setup script missing; skipping ES wiring." >&2\n'
        '  echo "         To finish the integration manually:" >&2\n'
        '  echo "           1. Open Splunk ES > Configure > General > Mission Control / Adaptive Response." >&2\n'
        '  echo "           2. Set the SOAR endpoint to ${SOAR_TENANT_URL}." >&2\n'
        '  echo "           3. Paste the token value from ${TOKEN_FILE} into the SOAR token field." >&2\n'
        '  exit 0\n'
        'fi\n'
        '# Preview the YAML spec; operator runs --apply manually after review.\n'
        'bash "${ES_CONFIG}" --spec "${SPEC_PATH}" --mode preview\n'
        'echo ""\n'
        'echo "Preview complete. Re-run with --mode apply --apply when satisfied:"\n'
        'echo "  bash ${ES_CONFIG} --spec ${SPEC_PATH} --mode apply --apply"\n'
    )
    out["configure-phantom-endpoint.sh"] = make_script(es_body)

    return out


def render_validate(args: argparse.Namespace) -> str:
    body = (
        _SOAR_LIB_DIR_BLOCK
        + f'SOAR_PLATFORM="${{SOAR_PLATFORM:-{args.soar_platform}}}"\n'
        + f'SOAR_TENANT_URL="${{SOAR_TENANT_URL:-{args.soar_tenant_url}}}"\n'
        + 'TOKEN_FILE="${SOAR_API_TOKEN_FILE:-/tmp/soar_api_token}"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/credential_helpers.sh"\n'
        + "# shellcheck disable=SC1091\n"
        + 'source "${LIB_DIR}/soar_helpers.sh"\n\n'
        + 'if [[ -z "${SOAR_TENANT_URL}" ]]; then\n'
        + '  echo "ERROR: SOAR_TENANT_URL not set; export SOAR_TENANT_URL=https://soar:8443" >&2\n'
        + '  exit 1\n'
        + 'fi\n'
        + 'if [[ ! -s "${TOKEN_FILE}" ]]; then\n'
        + '  echo "ERROR: SOAR API token missing: ${TOKEN_FILE}" >&2\n'
        + '  exit 1\n'
        + 'fi\n\n'
        + 'TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)\n'
        + 'AUDIT_DIR="$(dirname "$0")/audit/${TIMESTAMP}"\n'
        + 'mkdir -p "${AUDIT_DIR}"\n'
        + 'chmod 0700 "${AUDIT_DIR}" 2>/dev/null || true\n\n'
        + '# Map each REST path to a deterministic, slash-prefixed output filename.\n'
        + '# /rest/system_info -> ${AUDIT_DIR}/rest_system_info.json (note the slash).\n'
        + '# soar_rest_call feeds the ph-auth-token to curl via -K <(...) so it\n'
        + '# never lands on argv. Output files are written under umask 077.\n'
        + 'fetch_rest() {\n'
        + '  local path="$1"\n'
        + '  local out_name\n'
        + '  out_name="$(echo "${path#/}" | tr "/?=&" "____" | sed "s/__*/_/g")"\n'
        + '  local out_path="${AUDIT_DIR}/${out_name}.json"\n'
        + '  ( umask 077 && soar_rest_call "${SOAR_TENANT_URL}" "${TOKEN_FILE}" GET "${path}" > "${out_path}" 2>/dev/null ) \\\n'
        + '    || ( umask 077 && echo "{}" > "${out_path}" )\n'
        + '  printf "%s" "${out_path}"\n'
        + '}\n\n'
        'fetch_rest /rest/system_info >/dev/null\n'
        'version_path="$(fetch_rest /rest/version)"\n'
        'fetch_rest /rest/license >/dev/null\n'
        'fetch_rest "/rest/ph_user?include_automation=1" >/dev/null\n\n'
        'if [[ "${SOAR_PLATFORM}" == "onprem-cluster" ]]; then\n'
        '  fetch_rest /rest/cluster_node >/dev/null\n'
        'fi\n\n'
        'ver=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(\\"version\\", \\"\\"))" "${version_path}" 2>/dev/null || echo "")\n'
        'if [[ -z "${ver}" ]]; then\n'
        '  echo "FAIL: SOAR /rest/version did not return a version. See ${AUDIT_DIR}/" >&2\n'
        '  exit 1\n'
        'fi\n'
        'echo "PASS: SOAR ${ver} reachable. Snapshot: ${AUDIT_DIR}"\n'
    )
    return make_script(body)


def render_metadata(args: argparse.Namespace) -> str:
    return json.dumps(
        {
            "skill": "splunk-soar-setup",
            "soar_platform": args.soar_platform,
            "soar_home": args.soar_home,
            "soar_https_port": args.soar_https_port,
            "soar_hosts": csv_list(args.soar_hosts),
            "soar_tenant_url": args.soar_tenant_url,
            "automation_broker": kv_dict(args.automation_broker),
            "splunk_side_apps": kv_dict(args.splunk_side_apps),
            "es_integration_readiness": args.es_integration_readiness == "true",
            "auth_file_ready": bool(args.auth_file and Path(args.auth_file).is_file()),
            "ca_cert_file_ready": bool(args.ca_cert_file and Path(args.ca_cert_file).is_file()),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def dry_run_payload(args: argparse.Namespace) -> dict:
    apps = kv_dict(args.splunk_side_apps)
    broker = kv_dict(args.automation_broker)
    broker_runtime = broker.get("runtime", "docker")
    if broker_runtime not in VALID_RUNTIMES:
        die(f"automation_broker runtime must be docker or podman: {broker_runtime!r}")
    return {
        "skill": "splunk-soar-setup",
        "dry_run": True,
        "server_install_supported": args.soar_platform in {"onprem-single", "onprem-cluster"},
        "soar_platform": args.soar_platform,
        "soar_tenant_url": args.soar_tenant_url,
        "apps": [
            {
                "app_id": "6361",
                "app_name": "splunk_app_soar",
                "label": "Splunk App for SOAR",
                "selected": apps.get("app_for_soar", "true") == "true",
            },
            {
                "app_id": "3411",
                "app_name": "phantom",
                "label": "Splunk App for SOAR Export",
                "selected": apps.get("app_for_soar_export", "true") == "true",
            },
        ],
        "automation_broker": {
            "selected": bool(broker),
            "runtime": broker_runtime,
            "image_source": broker.get("image_source", "dockerhub"),
            "handoff_only": False,
        },
        "handoff": {
            "auth_file_ready": bool(args.auth_file and Path(args.auth_file).is_file()),
            "ca_cert_file_ready": bool(args.ca_cert_file and Path(args.ca_cert_file).is_file()),
            "cloud_onboarding": args.soar_platform == "cloud",
        },
        "rendered_surfaces": [
            "onprem-single",
            "onprem-cluster",
            "cloud",
            "automation-broker",
            "splunk-side",
            "es-integration",
        ],
    }


def render_readme(args: argparse.Namespace) -> str:
    return (
        "# Splunk SOAR Rendered Assets\n\n"
        f"Platform: `{args.soar_platform}`\n"
        f"SOAR home: `{args.soar_home}`\n"
        f"HTTPS port: `{args.soar_https_port}`\n"
        f"Tenant URL: `{args.soar_tenant_url or '(n/a)'}`\n\n"
        "## Files\n\n"
        "- `onprem-single/{prepare-system.sh, install-soar.sh, post-install-checklist.md}`\n"
        "- `onprem-cluster/{make-cluster-node.sh, backup.sh, restore.sh, external-services/...}`\n"
        "- `cloud/{onboarding-checklist.md, jwt-token-helper.sh, ip-allowlist.json, apply-allowlist.sh, automation-user.sh}`\n"
        "- `automation-broker/{docker-compose.yml | podman-compose.yml, install.sh, add-ca-certificate.sh, preflight.sh}`\n"
        "- `splunk-side/{install-app-for-soar.sh, install-app-for-soar-export.sh, configure-phantom-endpoint.sh}`\n"
        "- `validate.sh`\n\n"
        "## Next steps\n\n"
        "1. After SOAR is reachable, run `splunk-side/configure-phantom-endpoint.sh` to wire ES Mission Control.\n"
        "2. If Automation Broker connects to a Splunk Cloud stack, promote the stub at `handoffs/acs-allowlist.json` into a `splunk-cloud-acs-allowlist-setup` plan and apply it.\n"
    )


def render_handoffs(args: argparse.Namespace) -> dict:
    return {
        "handoffs/acs-allowlist.json": json.dumps(
            {
                "feature": "search-api",
                "subnets": [],
                "comment": "Replace subnets with the Automation Broker host's egress IP(s) and feed into splunk-cloud-acs-allowlist-setup.",
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
    }


def render_all(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    files = []

    write_file(output_dir / "README.md", render_readme(args))
    files.append("README.md")
    write_file(output_dir / "metadata.json", render_metadata(args))
    files.append("metadata.json")
    write_file(output_dir / "validate.sh", render_validate(args), executable=True)
    files.append("validate.sh")

    for name, content in render_onprem_single(args).items():
        path = output_dir / "onprem-single" / name
        write_file(path, content, executable=name.endswith(".sh"))
        files.append(f"onprem-single/{name}")

    for rel, content in render_onprem_cluster(args).items():
        path = output_dir / "onprem-cluster" / rel
        write_file(path, content, executable=rel.endswith(".sh"))
        files.append(f"onprem-cluster/{rel}")

    for name, content in render_cloud(args).items():
        path = output_dir / "cloud" / name
        write_file(path, content, executable=name.endswith(".sh"))
        files.append(f"cloud/{name}")

    for name, content in render_automation_broker(args).items():
        path = output_dir / "automation-broker" / name
        write_file(path, content, executable=name.endswith(".sh"))
        files.append(f"automation-broker/{name}")

    for name, content in render_splunk_side(args).items():
        path = output_dir / "splunk-side" / name
        write_file(path, content, executable=name.endswith(".sh"))
        files.append(f"splunk-side/{name}")

    for rel, content in render_handoffs(args).items():
        path = output_dir / rel
        write_file(path, content)
        files.append(rel)

    return {"render_dir": str(output_dir), "files": sorted(files)}


def main() -> None:
    args = parse_args()
    if args.dry_run:
        if args.json:
            print(json.dumps(dry_run_payload(args), indent=2, sort_keys=True))
        else:
            print(f"Platform: {args.soar_platform}")
        return
    result = render_all(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(result['files'])} SOAR asset(s) to {result['render_dir']}")
        for name in result["files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()
