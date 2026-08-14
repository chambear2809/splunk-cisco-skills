# Agent Control deployment boundary

This skill owns Kubernetes packaging for the optional Agent Control service:
chart identity, values overlay, database bootstrap decision, migration/hook
inventory, HPA/PDB/NetworkPolicy intent, direct route, UI proxy, feature flag,
and deployment-order evidence. It does not create runtime controls or Splunk
sinks.

The default topology is the standalone Helm release `agent-control`. The values
key is `galileo_services.agent_control`. Some exact umbrella packages may own the
component instead; only hash-bound package evidence may select that mode. An
umbrella-owned component produces an overlay for a new parent stack bundle and
must never be installed a second time.

The default Kubernetes Secret contracts are:

| Secret | Required key(s) | Purpose |
|---|---|---|
| `postgres` | `GALILEO_POSTGRES_USER`, `GALILEO_POSTGRES_PASSWORD` | Agent Control database access |
| `api-secret` | `GALILEO_API_SECRET_KEY` | Internal Galileo API authentication |

Override names or keys only when the exact chart schema and CSE-approved values
prove the alternate contract. Do not place Secret data in the intake or render.

Direct service health is HTTP `/health` on port `8000`. Browser Controls traffic
uses the UI same-origin `/api/agent-control/*` proxy. Public backend docs are
validated only on the direct route or a local port-forward because the UI proxy
intentionally blocks them.

Standalone preflight emits canonical
`galileo-on-prem-child-rendered-image-inventory/v1` evidence to the explicitly
new private path passed by `--image-evidence-file`, and canonical
`galileo-on-prem-child-rendered-endpoint-inventory/v1` evidence to
`--endpoint-evidence-file`. The latter contains only normalized host[:port],
sanitized purpose/source identifiers, and exact chart/input/render/target
bindings; Secret URLs are decoded only in memory. Air-gap preparation consumes
both with the exact immutable child bundle.

This skill never installs, upgrades, rolls back, or uninstalls the release.
Every historical `--apply-*` mode fails before kubeconfig, bundle, or process
access. Hand `lifecycle.json` plus fresh preflight/image/endpoint evidence to a
Galileo/CSE joint-session operator.
