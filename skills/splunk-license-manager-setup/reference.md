# Splunk License Manager Reference

## Research Basis

This skill follows current Splunk Enterprise license documentation (10.0+):

- A license manager is a central license repository; remote instances become
  license peers. The "license master" terminology was renamed to "license
  manager" in 9.x — both terms appear in the docs and this skill renders
  `manager_uri` for 9.x+ peers.
- License compatibility: manager Splunk version must be **>=** peer Splunk
  version at the major/minor release level. Patch-level differences are
  irrelevant.
- License REST endpoints under `/services/licenser/`:
  `groups`, `licenses`, `localpeer`, `messages`, `peers`, `pools`, `stacks`,
  `usage`.
- Volume-based and infrastructure (vCPU) Enterprise licenses cannot stack.
  Free / Trial / Developer / Dev-Test cannot stack with anything.
- License install is `splunk add licenses /path/to/<file>.lic` (CLI) or
  `POST /services/licenser/licenses` (REST).
- License peer configuration is `splunk edit licenser-localpeer -manager_uri
  https://lm:8089` (writes `[license] manager_uri = ...` in `server.conf`).
- License pools are POST/PUT/DELETE on `/services/licenser/pools` with
  fields: `name`, `quota` (bytes or `MAX`), `slaves` (peer GUID list or `*`),
  `stack_id`, `description`.
- License messages have categories `pool_over_quota`, `stack_over_quota`,
  `orphan_peer`, `pool_warning_count`, `pool_violated_peer_count`,
  `license_window` with severity INFO / WARN / ERROR.

Official references:

- Configure a license manager:
  <https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.0/configure-splunk-licenses/configure-a-license-manager>
- Configure a license peer:
  <https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.0/configure-splunk-licenses/configure-a-license-peer>
- Types of Splunk Enterprise licenses:
  <https://docs.splunk.com/Documentation/Splunk/latest/Admin/TypesofSplunklicenses>
- License endpoint descriptions (REST):
  <https://help.splunk.com/en/splunk-enterprise/rest-api-reference/10.2/license-endpoints>
- Manage licenses from the CLI:
  <https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.2/manage-splunk-licenses/manage-licenses-from-the-cli>
- License usage report view:
  <https://help.splunk.com/en/data-management/splunk-enterprise-admin-manual/10.0/license-usage-report-view/about-the-splunk-enterprise-license-usage-report-view>

## License Type Matrix

| Type                     | Daily quota | Duration  | Stacks?     | Notes                                                                         |
|--------------------------|-------------|-----------|-------------|-------------------------------------------------------------------------------|
| Volume Enterprise        | per file    | per file  | with volume | Blocks search if stack < 100 GB and warnings exceed limit.                    |
| Infrastructure (vCPU)    | n/a         | per file  | with infra  | vCPU-based; cannot stack with volume.                                         |
| Trial (auto-generated)   | 500 MB      | 60 days   | no          | Generated on install; not for distributed deployment.                         |
| Free                     | 500 MB      | perpetual | no          | Disables auth, clustering, scheduled searches, alerts, etc.                    |
| Dev/Test                 | 50 GB       | 6 months  | no          | Personalized; for paying customers' pre-prod testing only.                    |
| Developer                | 10 GB       | 6 months  | no          | Splunk Developer Agreement; not production.                                   |
| Pre-release              | varies      | varies    | no          | Beta program only; incompatible with GA releases.                             |
| Build Partner            | 50 GB       | renewable | no          | Splunk Partnerverse partners (formerly TAP).                                  |
| Workload Pricing-aware   | n/a         | per file  | n/a         | Skill renders the Workload Pricing label correctly when present.              |

## Terminology Shift

- Splunk 8.x and earlier: "license master", `master_uri`, `License-Master-URI`.
- Splunk 9.x and later: "license manager", `manager_uri`.

This skill renders `manager_uri` by default. When peers report Splunk < 9.x,
the rendered `configure-peer.sh` falls back to `master_uri` automatically.

## License Groups

Only one license group is active per instance. Switch via:

```
POST /services/licenser/groups/{Enterprise|Forwarder|Free|Trial|Download-Trial}
     -d is_active=1
```

The Free group disables: authentication, distributed search, indexer
clustering, scheduled searches, scheduled alerts, summary indexing, deployment
server. The skill prints these restrictions when activating the Free group so
operators understand the trade-off.

## License Pools

Pool definitions:

- `name` — pool identifier.
- `stack_id` — `enterprise` / `forwarder` / `download-trial` / `free` / `dev`.
- `quota` — byte count (e.g. `107374182400` for 100 GB) or the special string
  `MAX` (entire stack quota).
- `slaves` — comma-separated peer GUID list, or `*` for all peers in stack.
- `description` — optional human label.

Preflight ensures the sum of all explicit pool quotas does not exceed the
parent stack's total quota.

## License Messages

Categories (per the REST endpoint):

| Category                  | Severity              | Meaning                                                              |
|---------------------------|-----------------------|----------------------------------------------------------------------|
| `license_window`          | INFO/WARN/ERROR       | Approaching or exceeding the rolling 30-day violation window.        |
| `pool_over_quota`         | WARN/ERROR            | A pool is over its allocated quota.                                  |
| `stack_over_quota`        | ERROR                 | The stack itself is over total daily quota.                          |
| `orphan_peer`             | WARN                  | A peer is reporting usage but is not assigned to any pool.           |
| `pool_warning_count`      | WARN                  | A pool has accumulated warnings.                                     |
| `pool_violated_peer_count`| ERROR                 | A pool has peers that exceeded the violation threshold.              |

Validate fails on any ERROR message; warns on WARN.

## High Availability

Splunk does not natively cluster license managers. The recommended pattern is:

- Run a primary license manager on the cluster manager (or another control
  node).
- Maintain a cold-standby license manager on a separate host with the same
  Splunk version and the same `pass4SymmKey`.
- Use a DNS record (e.g. `lm.example.com`) for `manager_uri`.
- On failover, install the same `.lic` files on the standby and update the
  DNS record.

The rendered `peers/<host>/peer-server.conf` always uses the user-supplied
`--license-manager-uri`, so DNS-based failover requires no peer changes.

## Squash Threshold

The localpeer `squash_threshold` (default 2000) controls when source/host
combinations are squashed in usage rows. Tune it down for low-cardinality
environments to retain detail; tune it up for high-cardinality environments
to reduce manager load. The skill surfaces the current value in the audit
snapshot but does not modify it (it lives in `[license]` localpeer config and
is rarely changed).

## Out of Scope

- Splunk Cloud licensing (Splunk-managed).
- Commercial entitlement procurement / renewal (vendor process).
- License upgrade across major Splunk Enterprise releases (run after Splunk
  upgrade via [`skills/splunk-enterprise-host-setup`](../splunk-enterprise-host-setup/SKILL.md)).
