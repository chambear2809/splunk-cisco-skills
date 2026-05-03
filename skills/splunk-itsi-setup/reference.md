# Splunk ITSI Setup — Reference

Operational reference for the install-and-validate workflow exposed by
[`SKILL.md`](SKILL.md). The skill installs the **Splunk IT Service
Intelligence** (ITSI) bundle and verifies the post-install state. Live ITSI
content management (entities, services, KPIs, NEAPs, content packs, service
trees) lives in the separate `splunk-itsi-config` skill.

## Product Identity

| Property | Value |
|---|---|
| Product name | Splunk IT Service Intelligence |
| Premium license | Required (separate from Splunk Enterprise license) |
| Splunkbase listing | [App ID 1841](https://splunkbase.splunk.com/app/1841) |
| Primary internal app | `SA-ITOA` (the engine; UI ships in `itsi`) |
| Bundled apps | `SA-ITOA`, `itsi`, `SA-UserAccess`, `SA-ITSI-Licensechecker`, plus optional `DA-ITSI-*` content packs |
| Deployment placement | Search-tier role (search head, SHC member via deployer) |

Refer to Splunk Docs for canonical version compatibility:

- [Splunk ITSI install / upgrade overview](https://docs.splunk.com/Documentation/ITSI/latest/Install/Overview)
- [ITSI version compatibility matrix](https://docs.splunk.com/Documentation/ITSI/latest/Install/Hardwareandsoftwarerequirements)
- [Splunk Apps and ITSI Cloud requirements](https://docs.splunk.com/Documentation/ITSI/latest/Install/Splunkclouddeploymentguidelines)

## Topology Placement

| Role | Place ITSI here? |
|---|---|
| Standalone search head | Yes — ITSI installs and runs end-to-end |
| Search Head Cluster (SHC) member | Yes — install via the SHC deployer, never directly on members |
| SHC deployer | Stage the bundle here; do not enable ITSI scheduler activity |
| Indexer cluster peer | No — ITSI does not run on indexers; only the relevant TAs (CIM, OS, etc.) belong on indexers |
| Cluster manager / license manager | No |
| Heavy forwarder | No |
| Splunk Cloud Victoria | Self-service install for eligible stacks; otherwise file a Splunk Cloud Support ticket |
| Splunk Cloud Classic | Splunk Cloud Support managed install |

## Splunk Cloud vs Enterprise Differences

| Aspect | Splunk Enterprise | Splunk Cloud |
|---|---|---|
| Install path | Splunkbase → REST `/services/apps/local` (or Deployer bundle for SHC) | ACS `apps install` for Victoria-eligible stacks; otherwise Splunk Cloud Support |
| Restart | Always required after install | ACS reports `restartRequired=true`; only call `acs restart current-stack` when set |
| KV Store sizing | Operator-managed | Stack-managed; review with Splunk Cloud Support before enabling many KPIs |
| Backup / restore | Local `splunk backup` workflow | Stack-managed; no operator-side backup steps |
| License application | Operator applies the ITSI license slice | Pre-applied at the stack level |

## Installed Apps After Bootstrap

| App | Purpose |
|---|---|
| `SA-ITOA` | Service definitions, KPIs, base searches, event management engine |
| `itsi` | UI: glass tables, service analyzer, deep dives |
| `SA-UserAccess` | Role-based access control for ITSI |
| `SA-ITSI-Licensechecker` | Validates the ITSI license slice |
| `DA-ITSI-CONTENT-*` | Optional content packs (separate Splunkbase listings) |

## REST / KV Surface Validated by `validate.sh`

The validator confirms presence of these signals:

| Endpoint | Purpose |
|---|---|
| `GET /services/apps/local/SA-ITOA` | App installed and enabled |
| `GET /services/apps/local/itsi` | UI app installed and enabled |
| `GET /servicesNS/nobody/SA-ITOA/storage/collections/config` | KV Store reachable for ITSI namespace |
| `GET /servicesNS/nobody/SA-ITOA/configs/conf-itsi/itoa` | Engine settings reachable |

## Key Operational Caveats

1. **License gate.** Install succeeds without a license, but core scheduler
   functionality is gated. Apply the ITSI license slice before declaring the
   deployment "ready."
2. **KV Store hygiene.** ITSI is KV-Store-heavy. Run
   `| rest /services/server/info splunk_server=local | fields kvStoreStatus`
   before bulk content load.
3. **Deployer push order on SHC.** Stage `SA-ITOA`, then dependent apps
   (`SA-UserAccess`, content packs). Apply the bundle, then validate from any
   member.
4. **ThousandEyes integration.** When `ta_cisco_thousandeyes` is also present,
   the alert action `thousandeyes_forward_splunk_events` becomes available and
   the `itsi_episodes` KV collection is shared with the integration. The
   ThousandEyes validator surfaces this as integration-readiness.
5. **Restart semantics.** Enterprise: `splunk restart` on the search head
   (members via SHC deployer push). Cloud: `acs status current-stack` first,
   only restart when ACS asks.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `SA-ITOA` missing after install | Splunkbase package didn't unpack into `etc/apps` (permissions, low disk) | Re-run `splunk-app-install` with `--source local` and the cached package |
| `validate.sh` reports KV Store down | KV Store didn't restart after upgrade | `splunk start kvstore` (Enterprise) or open a ticket (Cloud) |
| ITSI UI 500s on first open | License not applied or KV Store not seeded | Apply ITSI license; then `validate.sh` again |
| ACS install rejects ITSI | Stack is Classic or non-Victoria | File a Splunk Cloud Support case; do not attempt private upload |

## Related Skills

- [`splunk-itsi-config`](../splunk-itsi-config/SKILL.md) — declarative
  management of ITSI entities, services, KPIs, NEAPs, content packs.
- [`splunk-app-install`](../splunk-app-install/SKILL.md) — generic installer
  used internally by this skill.
- [`cisco-thousandeyes-setup`](../cisco-thousandeyes-setup/SKILL.md) —
  bidirectional alert-action integration with ITSI.
