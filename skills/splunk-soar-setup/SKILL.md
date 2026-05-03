---
name: splunk-soar-setup
description: >-
  Render, preflight, apply, and validate the full Splunk SOAR lifecycle:
  Splunk SOAR (On-prem) unprivileged single-instance install, On-prem cluster
  install with external services (PostgreSQL local or AWS RDS, GlusterFS,
  Elasticsearch, HAProxy), SOAR Cloud onboarding helper (JWT capture, IP
  allowlist, REST automation user provisioning), Splunk SOAR Automation
  Broker on Docker or Podman with FIPS detection, Splunk-side apps (Splunk
  App for SOAR Splunkbase 6361, Splunk App for SOAR Export Splunkbase 3411),
  and ES integration readiness via the existing Mission Control wiring. Use
  when the user asks to install Splunk SOAR On-prem, build a SOAR cluster,
  onboard SOAR Cloud, install Automation Broker, install splunk-side SOAR
  apps, or wire up SOAR with Splunk Enterprise Security.
---

# Splunk SOAR Setup

This skill covers every documented Splunk SOAR install path:

- **On-prem single instance** (unprivileged) — `soar-prepare-system` followed
  by `soar-install`.
- **On-prem cluster** (>= 3 nodes) — `make_cluster_node.pyc` plus external
  PostgreSQL / GlusterFS / Elasticsearch / HAProxy.
- **SOAR Cloud** — Splunk-provisioned tenant; the skill handles JWT capture,
  IP allowlist, REST automation-user / token creation, and Automation Broker
  install for connecting back to a private network.
- **Splunk-side integration** — installs Splunk App for SOAR (Splunkbase
  6361) and Splunk App for SOAR Export (Splunkbase 3411) via the existing
  [`skills/splunk-app-install`](../../skills/splunk-app-install/SKILL.md)
  skill.
- **ES integration readiness** — calls
  [`skills/splunk-enterprise-security-config`](../../skills/splunk-enterprise-security-config/SKILL.md)
  `integrations.soar` engine path.

## Agent Behavior — Credentials

Never paste passwords, JWT tokens, or `pgbouncer`/postgres passwords into
chat.

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/soar_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/soar_api_token
bash skills/shared/scripts/write_secret_file.sh /tmp/postgres_master_password
bash skills/shared/scripts/write_secret_file.sh /tmp/pgbouncer_password
```

The skill reads these via `--*-file` flags and never embeds the value in
rendered output.

## Quick Start

Render a single-instance unprivileged install:

```bash
bash skills/splunk-soar-setup/scripts/setup.sh \
  --phase render \
  --soar-platform onprem-single \
  --soar-home /opt/soar \
  --soar-https-port 8443 \
  --soar-hostname soar01.example.com \
  --soar-tgz /tmp/splunk_soar-unpriv-8.5.0.tgz
```

Render a 3-node cluster with external PostgreSQL on AWS RDS:

```bash
bash skills/splunk-soar-setup/scripts/setup.sh \
  --phase render \
  --soar-platform onprem-cluster \
  --soar-home /opt/soar \
  --soar-https-port 8443 \
  --soar-hosts soar01,soar02,soar03 \
  --soar-tgz /tmp/splunk_soar-unpriv-8.5.0.tgz \
  --external-pg "mode=rds,host=soar-db.cluster-xyz.us-east-1.rds.amazonaws.com,port=5432" \
  --external-gluster gluster01,gluster02 \
  --external-es es01,es02,es03 \
  --load-balancer haproxy01
```

Render a SOAR Cloud onboarding bundle and Automation Broker install:

```bash
bash skills/splunk-soar-setup/scripts/setup.sh \
  --phase render \
  --soar-platform cloud \
  --soar-tenant-url https://example.splunkcloudgc.com/soar \
  --soar-automation-token-file /tmp/soar_automation_token \
  --automation-broker "runtime=docker,fips=auto"
```

Apply Splunk-side apps:

```bash
bash skills/splunk-soar-setup/scripts/setup.sh \
  --phase splunk-side-apps \
  --splunk-side-apps "app_for_soar=true,app_for_soar_export=true"
```

Validate (single instance):

```bash
bash skills/splunk-soar-setup/scripts/validate.sh \
  --soar-platform onprem-single \
  --soar-tenant-url https://soar01.example.com:8443 \
  --soar-api-token-file /tmp/soar_api_token
```

## What It Renders

Under `splunk-soar-rendered/`:

- `onprem-single/{prepare-system.sh, install-soar.sh, post-install-checklist.md}`
- `onprem-cluster/{make-cluster-node.sh, backup.sh, restore.sh}`
- `onprem-cluster/external-services/{postgres-rds.tf, postgres-local.sh, gluster-volume.sh, elasticsearch.yml, haproxy.cfg}`
- `cloud/{onboarding-checklist.md, jwt-token-helper.sh, ip-allowlist.json, apply-allowlist.sh, automation-user.sh}`
- `automation-broker/{docker-compose.yml, podman-compose.yml, install.sh, add-ca-certificate.sh, preflight.sh}`
- `splunk-side/{install-app-for-soar.sh, install-app-for-soar-export.sh, configure-phantom-endpoint.sh}`
- `validate.sh`

## Out of Scope

- SOAR Cloud tenant provisioning (Splunk-managed; users get an invite from
  Splunk).
- Custom playbook authoring (use SCM/Git outside this skill).
- Vendor-specific SOAR connector apps (catalog-aware, not installed).
- SOAR licensing (commercial, separate from Splunk Enterprise licensing).
- Multi-tenant SOAR On-prem (Splunk Professional Services).
- SOAR Cloud → On-prem repatriation.

## References

- [reference.md](reference.md) for cluster topology, external-services
  setup, FIPS handling, REST `automation` user model, ES integration map,
  and backup/restore flow.
- [template.example](template.example) for the non-secret intake worksheet.
