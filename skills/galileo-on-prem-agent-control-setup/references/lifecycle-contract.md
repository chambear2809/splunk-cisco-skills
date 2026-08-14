# Lifecycle contract

The renderer emits an immutable, non-secret contract. In standalone mode,
preflight binds the handoff to the bundle hash, private kubeconfig snapshot,
cluster identity, namespace UID, release, redacted input/render contracts, and
fresh evidence. The skill never executes the later mutation. In umbrella mode,
only the exact parent Stack handoff may consume the emitted overlay.

Required order:

1. Confirm `api` and `authz` are healthy and the internal authorization path is
   reachable.
2. Confirm PostgreSQL connectivity and the named Secret/key contracts.
3. Have the Galileo/CSE operator apply either the standalone `agent-control`
   release or a parent-stack overlay, never both.
4. Have the operator apply the optional direct route after the service.
5. Have the operator upgrade/restart UI so it receives
   `GALILEO_AGENT_CONTROL_API_CLUSTER_URL`.
6. Have the operator enable the `agent_control` feature flag at the declared
   source. A Helm
   environment override wins over local and central JSON.
7. Validate rollout, `/health`, direct-route TLS, UI proxy, docs policy, HPA,
   PDB, and NetworkPolicy.

For the NGINX route chart, the documented enable key is
`galileo_infra.ingress_nginx.agent_control_route.enabled`. For Gateway API it is
`galileo_infra.gateway_routes.routes.agent-control.enabled`. A customer-managed
proxy routes to Service `agent-control` on port `8000`. Creating a route does not
create DNS.

All install, upgrade, rollback, and uninstall execution is handoff-only.
Database migrations may be irreversible; require
the prior immutable bundle, backup evidence, release-note compatibility, and
Galileo approval before a Galileo/CSE operator session performs rollback.

The immutable `lifecycle.json` names the blocked apply modes and exact evidence
packet for a Galileo/CSE joint session. Historical `--apply-*` CLI modes fail
before kubeconfig, bundle, Helm, kubectl, or state access. Evidence JSON is
duplicate-free, closed-schema, and canonical; parent and child live release
objects are recomputed during preflight rather than trusted from a file.
Secret input evidence persists only allowlisted leaf paths, scalar shapes, and
render influence. Raw Secret values, their unsalted hashes, and raw rendered
Secret hashes are never persisted; a process-local keyed HMAC protects only the
private snapshot copy, and the render hash replaces every scalar value with a
fixed type marker.

Every non-uninstall preflight also writes canonical
`galileo-on-prem-child-rendered-image-inventory/v1` evidence to a new private
operator-selected path. It covers ordinary, init, hook, Job, and test containers
and rejects every image not pinned with `@sha256:`. The external operator must
re-render and require the same redacted render and image inventory evidence
before mutation.
The inventory and structural render digest are derived from the API server's
strict server-dry-run response, so Kubernetes defaulting and dry-run-capable
admission mutations are included rather than trusting Helm's client output.
It also requires a new `--endpoint-evidence-file` containing canonical
`galileo-on-prem-child-rendered-endpoint-inventory/v1` evidence. Endpoint values
from private Secret inputs and rendered Secret data are processed only in
memory; only lowercase host[:port] and sanitized source/purpose identifiers are
persisted. The external operator must re-derive this inventory before Helm.

Packaged dependencies are recursively inspected (maximum four nested archive
levels) for hooks, persistence/finalizer risk, `lookup`, `tpl`, any root
`.Files`, `.Capabilities`, or `.Release` access, and random/UUID/clock,
environment, DNS, crypto, or indirect root-access helpers. Any such construct in a parent or dependency template
blocks the handoff because a client render cannot prove the exact mutation
payload; obtain a deterministic chart and Galileo review. Render validation
requires exactly one reviewed Ingress rule host and TLS host/Secret binding, or
exactly one HTTPRoute hostname. Wildcards, suffix substitutions, extra hosts,
hostless default backends, and host-override annotations fail closed.
