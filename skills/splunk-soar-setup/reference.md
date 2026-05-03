# Splunk SOAR Reference

## Research Basis

- Splunk SOAR (On-prem) 8.5+ supports unprivileged installs from a TGZ
  distribution (`splunk_soar-unpriv-<version>.tgz`).
- Two-stage install: `sudo ./soar-prepare-system --splunk-soar-home <home>
  --https-port <port>` then `./soar-install --splunk-soar-home <home>
  --https-port <port>` as the unprivileged user.
- Cluster install uses `make_cluster_node.pyc` per node with the same
  username and install directory across all nodes.
- External services for cluster: PostgreSQL 15.x (local or AWS RDS, with a
  `pgbouncer` user superuser-grant), GlusterFS, Elasticsearch 8.11.4 /
  8.19.4 / 8.3.3, HAProxy.
- FIPS detection uses `/proc/sys/crypto/fips_enabled`.
- `soar-prepare-system --port-forward` exposes port 443 in addition to
  `--https-port` (single instance only).
- REST users: `normal` and `automation`. Only `automation` users hold
  long-lived REST tokens (consumed by Splunk-side apps and Automation
  Broker).
- Automation Broker is a container delivered for Docker (>= 20.10.2) and
  Podman (>= 4.1.0) with Docker Compose. FIPS mode auto-enables when the
  host kernel is in FIPS mode.
- Splunkbase IDs:
  - 6361 — Splunk App for SOAR (`splunk_app_soar`)
  - 3411 — Splunk App for SOAR Export (`phantom`)
- ES integration uses Mission Control: ES configures `phantom_endpoint`,
  `phantom_token`, `notable_event_forwarding`, and Adaptive Response
  actions.
- Backup/restore: `phenv python backup.pyc --all` (single) and `ibackup.pyc`
  (external DB / cluster).

Official references:

- Install Splunk SOAR (On-prem) as unprivileged user:
  <https://help.splunk.com/en/splunk-soar/soar-on-premises/install-and-upgrade-soar-on-premises/8.5.0/install-splunk-soar-on-premises/install-splunk-soar-on-premises-as-an-unprivileged-user>
- General system requirements:
  <https://help.splunk.com/en?resourceId=SOARonprem_Install_Requirements>
- Create a Splunk SOAR (On-prem) cluster using an unprivileged installation:
  <https://help.splunk.com/en/splunk-soar/soar-on-premises/install-and-upgrade-soar-on-premises/8.5.0/build-a-splunk-soar-on-premises-cluster/create-a-splunk-soar-on-premises-cluster-using-an-unprivileged-installation>
- Run make_cluster_node.pyc:
  <https://help.splunk.com/en/splunk-soar/soar-on-premises/install-and-upgrade-soar-on-premises/8.5.0/build-a-splunk-soar-on-premises-cluster/run-make_cluster_node.pyc>
- Set up an external PostgreSQL server:
  <https://help.splunk.com/en/splunk-soar/soar-on-premises/install-and-upgrade-soar-on-premises/8.5.0/run-splunk-soar-on-premises-using-external-services/set-up-an-external-postgresql-server>
- Splunk SOAR Automation Broker system requirements:
  <https://help.splunk.com/en/splunk-soar/splunk-automation-broker/install-splunk-soar-automation-broker>
- Splunk SOAR (Cloud) onboarding:
  <https://docs.splunk.com/Documentation/SOAR/current/Admin/FirstTimeLoginOnboarding>
- Using the REST API reference for Splunk SOAR (On-premises):
  <https://help.splunk.com/en/splunk-soar/soar-on-premises/rest-api-reference/8.5.0/using-the-splunk-soar-rest-api/using-the-rest-api-reference-for-splunk-soar-on-premises>
- REST User (ph_user):
  <https://help.splunk.com/en/splunk-soar/soar-on-premises/rest-api-reference/8.5.0/user-management-endpoints/rest-user>

## REST Automation User Model

The Splunk SOAR REST API supports two user types:

- `normal` — interactive analyst account; not designed for long-lived tokens.
- `automation` — service account excluded from `/rest/ph_user` by default.
  Surface via `?include_automation=1`. Splunk-side apps and Automation
  Broker should always consume an `automation` token.

The skill renders `cloud/automation-user.sh` (and the equivalent for
on-prem) that:

1. Creates an `automation` user via `POST /rest/ph_user` with
   `type=automation`.
2. Mints a long-lived token via `POST /rest/ph_user/<id>/token`.
3. Writes the returned token to a chmod 600 file via `write_secret_file.sh`.

## Cluster External Services

| Service       | Default                       | Render artifact                                          |
|---------------|--------------------------------|----------------------------------------------------------|
| PostgreSQL    | 15.3 local install            | `external-services/postgres-local.sh`                                                       |
| PostgreSQL    | AWS RDS                       | `external-services/postgres-rds.tf` (Terraform)                                             |
| GlusterFS     | distributed-replicated volume | `external-services/gluster-volume.sh`                                                       |
| Elasticsearch | 8.11.4 / 8.19.4 / 8.3.3       | `external-services/elasticsearch.yml`                                                       |
| HAProxy       | TCP front-end                 | `external-services/haproxy.cfg`                                                             |

## FIPS Mode

The skill probes `/proc/sys/crypto/fips_enabled`:

- `1` — kernel is in FIPS mode; SOAR install runs in FIPS mode automatically.
- `0` — kernel is not in FIPS mode; the skill proceeds without FIPS unless
  `--soar-fips require` is set, in which case it fails fast.
- Automation Broker inherits FIPS from the host kernel automatically.

## ES Integration Map

```
Splunk ES                                Splunk SOAR
+-----------------+                      +----------------+
| Mission Control |<---phantom_endpoint--| /rest/...      |
| Adaptive Resp.  |---notable forward--->| Cases / Events |
+-----------------+                      +----------------+
```

The `splunk-side/configure-phantom-endpoint.sh` script delegates to
`splunk-enterprise-security-config integrations.soar` so the wiring lives
in one place.

## Hand-off Contracts

- **SOAR On-prem on Splunk Cloud** — emits an allowlist plan stub at
  `splunk-soar-rendered/handoffs/acs-allowlist.json` for the Automation
  Broker egress IP targeting the `search-api` ACS feature.
- **Splunk-side apps** — calls `splunk-app-install` for each Splunkbase ID
  rather than re-implementing app install.
- **ES** — calls `splunk-enterprise-security-config integrations.soar`.

## Out of Scope

- SOAR Cloud tenant provisioning (Splunk-managed; users get an invite from
  Splunk).
- Custom playbook authoring (use SCM/Git outside this skill).
- Vendor-specific SOAR connector apps (catalog-aware, not installed).
- SOAR licensing (commercial; separate from Splunk Enterprise licensing).
- Multi-tenant SOAR On-prem (Splunk Professional Services).
- SOAR Cloud → On-prem repatriation.
