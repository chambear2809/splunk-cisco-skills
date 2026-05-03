# Splunk Cloud ACS Allowlist Reference

## Research Basis

This skill follows current Splunk Cloud ACS documentation:

- The Admin Config Service (ACS) API exposes
  `access/{feature}/ipallowlists` (IPv4) and
  `access/{feature}/ipallowlists-v6` (IPv6) endpoints with GET / POST / DELETE
  verbs.
- Seven feature types are supported: `acs`, `search-api`, `hec`, `s2s`,
  `search-ui`, `idm-api`, `idm-ui`.
- AWS subnet limits are 200 per individual feature and 230 per allow-list
  group (search-head, indexer, IDM, single-instance).
- GCP subnet limits are 200 per individual feature.
- The default IP allow list is open (`0.0.0.0/0`) for most features; closed by
  default for `search-api`, and closed by default for `search-ui` on PCI and
  HIPAA compliance stacks.
- ACS is not supported on FedRAMP High deployments — allowlist edits there
  must go through Splunk Support.
- Splunk publishes an explicit warning that adding subnets to the `acs`
  feature allowlist can lock you out of Splunk Web features that depend on
  ACS: IP allowlist (IPv4 and IPv6), Federated Search, Maintenance Windows in
  the CMC app, Observability APIs, and Limits.
- ACS API access requires the `sc_admin` role (or equivalent capability set
  per the capabilities documentation).
- The Splunk Cloud Platform Terraform Provider (`splunk/scp`) supports ACS IP
  allow list operations and can be used as an alternative or alongside this
  skill.

Official references:

- IP allow list configuration:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.3.2512/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/configure-ip-allow-lists-for-splunk-cloud-platform>
- ACS API endpoint reference:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.0.2503/admin-config-service-acs-api-endpoint-reference/admin-config-service-acs-api-endpoint-reference>
- ACS CLI:
  <https://docs.splunk.com/Documentation/SplunkCloud/latest/Config/ACSCLI>
- Manage ACS API access with capabilities:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.3.2512/using-the-admin-config-service-acs--api/manage-acs-api-access-with-capabilities>
- Splunk Cloud Platform Terraform Provider (`splunk/scp`):
  <https://registry.terraform.io/providers/splunk/scp/latest>

## Feature Surface

| Feature      | Port      | IPv4 default     | Notes                                                                        |
|--------------|-----------|------------------|------------------------------------------------------------------------------|
| `acs`        | n/a       | open (`0.0.0.0/0`) | IPv4 only. Restrict carefully — see Lock-out protection below.             |
| `search-api` | 8089      | closed            | REST/SDK access to search heads. Required by this skill itself.            |
| `hec`        | 443       | open              | HTTP Event Collector data ingestion.                                        |
| `s2s`        | 9997      | open              | Splunk-to-Splunk forwarder traffic.                                         |
| `search-ui`  | 80/443    | open (closed on PCI/HIPAA) | Search head Web UI access. PCI and HIPAA stacks ship with this closed by default. |
| `idm-api`    | 8089      | open              | Inputs Data Manager API. Only present on stacks with IDM.                   |
| `idm-ui`     | 443       | open              | Inputs Data Manager UI. Only present on stacks with IDM.                    |

The default state is invisible to GET until a subnet is explicitly added to
the feature; the skill displays this as `(default open)` or `(default closed)`
in the audit output.

## AWS vs GCP Subnet Limits

AWS deployments enforce per-group limits in addition to per-feature limits:

| Group           | ACS features included      | Per-group subnet cap |
|-----------------|----------------------------|----------------------|
| Search head     | `search-api`, `search-ui`  | 230                  |
| Indexer         | `hec`, `s2s`               | 230                  |
| IDM             | `idm-api`, `idm-ui`        | 230                  |
| Single instance | all four search/index ones | 230                  |

Per-feature cap on AWS is 200. GCP enforces 200 per feature with no group cap.
Preflight rejects plans that exceed either bound up front so apply never
returns 4xx.

## Lock-out Protection

Adding subnets to the `acs` feature allowlist for the first time can lock
operators out of these Splunk Web features that depend on ACS:

- IP allowlist (IPv4 and IPv6) — the very feature this skill manages.
- Federated Search.
- Maintenance Windows (CMC app).
- Observability APIs.
- Limits.

To prevent this, the rendered `preflight.sh` refuses to apply unless the
operator's current public IP appears in the planned `acs` subnet list. Pass
`--allow-acs-lockout` (sets `ALLOW_ACS_LOCKOUT=true` in the rendered plan) to
override after explicit confirmation.

`search-api` is also auto-protected via the existing
`acs_ensure_search_api_access` helper from
[`skills/shared/lib/acs_helpers.sh`](../../skills/shared/lib/acs_helpers.sh):
the operator's `/32` is added if missing before the skill issues any other
allowlist call (chicken-and-egg).

## IPv6 Behavior Notes

- `access/{feature}/ipallowlists-v6` GET / POST mirror the IPv4 surface.
- DELETE supports two forms: a single subnet appended to the URL
  (`.../ipallowlists-v6/<subnet>`) or a JSON body with a `subnets` array. The
  rendered `apply-ipv6.sh` uses the URL-appended form for single deletes and
  body form for batch deletes to avoid encoding-the-slash footguns.
- IPv6 and IPv4 share the same per-feature and per-group caps on AWS.

## VPN / Bastion Subnet Patterns

Common architecture templates that fit cleanly into this skill:

- **Single egress NAT** — one CIDR per environment; add to `s2s` and `hec`.
- **Dual-region NAT** — two `/32` or `/29` blocks; add to all data planes
  used by the regions.
- **Branch-office VPN** — the office VPN concentrator's egress block; add to
  `search-api` and `search-ui` for analyst access.
- **Bastion CIDR** — small bastion subnet that fronts admin tooling; add to
  `acs` and `search-api` and protect with `ALLOW_ACS_LOCKOUT=false`.

`reference.md` is the place to record the operator's chosen pattern so peers
can audit the intent.

## Out of Scope

- HEC token CRUD (lives in
  [`skills/splunk-hec-service-setup`](../splunk-hec-service-setup/SKILL.md)).
- Index management (handled by per-app skills via shared helpers).
- ACS limits / maintenance windows (separate ACS surfaces).
- FedRAMP High allowlist edits (must go through Splunk Support).

## Hand-off Contracts

Other skills emit allowlist plan stubs that this skill consumes:

- `splunk-edge-processor-setup` emits per-EP-instance public IP stubs targeting
  `s2s` and `hec`.
- `splunk-soar-setup` emits Automation Broker egress IP stubs targeting
  `search-api`.

Stubs are appended to `splunk-cloud-acs-allowlist-rendered/allowlist/plan.json`
under a `proposed_subnets` block; the operator promotes them into the active
plan before the next apply.
